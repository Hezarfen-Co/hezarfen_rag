"""API ↔ yerel sağlayıcı geçişi (#96 devamı).

NEDEN: rerank, GPU'yu isteyen **tek** parçadır (EXP-018: CPU'da 95,9 s; sorgu
embed 0,122 s, arama milisaniye). Uzak servise taşınırsa CPU yeter. Bu dosya
geçişin SESSİZ KALİTE/GÜVENLİK KAYBI üretmediğini sabitler.

En kritik test: rerank kapatıldığında **çekimserlik kapısı bozulur** ve servis
açılışta HATA vermelidir. Yapay skorlar hep 1,0'dan başladığı için
`contexts[0].score < 0,30` kuralı hiç tetiklenmez — ürün kitapta olmayan
soruya da cevap üretmeye çalışır. Sessizce devre dışı kalmış bir fail-closed
kapı, hiç olmayandan daha tehlikelidir: operatör korumalı sanır.
"""
import json
import unittest
from unittest import mock

import numpy as np

from src.embed.provider import (ApiEmbedder, EmbeddingUnavailable,
                                build_embedder)
from src.embed.provider import provider_warnings as embed_warnings
from src.rerank.provider import (ALLOW_UNCALIBRATED, ApiReranker, NoOpReranker,
                                 RerankUnavailable, build_reranker,
                                 check_abstain_compatibility)
from src.rerank.provider import provider_warnings as rerank_warnings


def _http(payload, status=200):
    """urlopen taklidi."""
    class _R:
        def read(self_inner):
            return json.dumps(payload).encode()
        def __enter__(self_inner):
            return self_inner
        def __exit__(self_inner, *a):
            return False
    return _R()


def _yanit(payload):
    """2xx gövdeli `urlopen` taklidi."""
    class _R:
        def read(self_inner):
            return json.dumps(payload).encode()

        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *a):
            return False

    return _R()


class GatewayBodyErrorTests(unittest.TestCase):
    """GEÇİT 2xx GÖVDESİNDE HATA DÖNDÜREBİLİR (Kilo/OpenRouter, yük altında HTTP
    200 + `{"error":{"code":503,...}}`).

    Kod durumuna bakan istemci bunu başarı sayar; `data` gelmeyince çıkan
    "beklenmeyen yanıt" mesajı gerçek nedeni (sağlayıcı yükü) gizler ve yeniden
    deneme hiç olmaz — gömme indeksinin KURULUŞU böyle düşer.
    """

    _VEKTOR = {"data": [{"index": 0, "embedding": [3.0, 4.0]}]}

    def _emb(self, **kw):
        return ApiEmbedder(base_url="https://ornek/v1", model="m",
                           api_key="k", **kw)

    def _yama(self, yanitlar):
        cagri = {"n": 0}

        def _say(istek, timeout=None):
            cagri["n"] += 1
            yanit = yanitlar[cagri["n"] - 1]
            if isinstance(yanit, BaseException):
                raise yanit
            return yanit

        return (mock.patch("urllib.request.urlopen", side_effect=_say),
                # create=True: düzeltme ÖNCESİ dosyada bu ad yok; o hâlde de
                # test DAVRANIŞSAL olarak düşsün (AttributeError ile değil).
                mock.patch("src.embed.provider.backoff_delay", return_value=0.0,
                           create=True),
                cagri)

    def test_govdede_gecici_hata_yeniden_denenir(self):
        yanitlar = [_yanit({"error": {"message": "Upstream error from Nvidia: "
                                                 "Service temporarily overloaded",
                                      "code": 503}}),
                    _yanit(self._VEKTOR)]
        p1, p2, cagri = self._yama(yanitlar)
        with p1, p2:
            m = self._emb(dim=2).embed(["x"])
        self.assertEqual(cagri["n"], 2)
        self.assertAlmostEqual(float(np.linalg.norm(m[0])), 1.0, places=5)

    def test_govdede_kalici_hata_ilk_denemede_saglayicinin_mesajiyla_biter(self):
        yanitlar = [_yanit({"error": {"message": "model bulunamadi", "code": 400}})]
        p1, p2, cagri = self._yama(yanitlar)
        with p1, p2:
            with self.assertRaises(EmbeddingUnavailable) as ctx:
                self._emb(dim=2).embed(["x"])
        self.assertEqual(cagri["n"], 1)
        self.assertIn("model bulunamadi", str(ctx.exception))

    def test_govdede_dizge_bicimi_hata_gecici_sayilir(self):
        yanitlar = [_yanit({"error": "temporary upstream failure"}),
                    _yanit(self._VEKTOR)]
        p1, p2, cagri = self._yama(yanitlar)
        with p1, p2:
            self._emb(dim=2).embed(["x"])
        self.assertEqual(cagri["n"], 2)

    def test_gercek_http_5xx_yeniden_denenir(self):
        import urllib.error
        yanitlar = [urllib.error.HTTPError("u", 503, "m", {}, None),
                    _yanit(self._VEKTOR)]
        p1, p2, cagri = self._yama(yanitlar)
        with p1, p2:
            self._emb(dim=2).embed(["x"])
        self.assertEqual(cagri["n"], 2)


class FactoryTests(unittest.TestCase):
    def test_local_is_the_default(self):
        """Ölçülmüş bütün kalite sayıları yerel yola ait; varsayılan
        değişirse raporlar sessizce başka bir ürünü tarif eder."""
        from src.embed.embedder import BGEM3Embedder
        from src.rerank.reranker import BGEReranker
        self.assertIsInstance(build_embedder(provider="local"), BGEM3Embedder)
        self.assertIsInstance(build_reranker(provider="local"), BGEReranker)

    def test_unknown_provider_is_refused(self):
        for f in (build_embedder, build_reranker):
            with self.subTest(f=f.__name__):
                with self.assertRaises(ValueError):
                    f(provider="magic")

    def test_api_without_config_is_refused_not_silently_local(self):
        """Yanlış yapılandırma sessizce yerele düşerse operatör API'ye
        geçtiğini sanır ve GPU'suz makinede 96 s bekler."""
        with self.assertRaises(ValueError):
            build_embedder(provider="api", base_url="", model="")
        with self.assertRaises(ValueError):
            build_reranker(provider="api", url="")


class AbstainGateCompatibilityTests(unittest.TestCase):
    """ASIL TEST — sessizce devre dışı kalan fail-closed kapı."""

    def test_uncalibrated_provider_blocks_startup(self):
        with self.assertRaises(RuntimeError) as ctx:
            check_abstain_compatibility(NoOpReranker(), abstain_score=0.30)
        metin = str(ctx.exception)
        for ipucu in ("calibrate_abstain_cli", "RAG_ABSTAIN_SCORE=0",
                      "RAG_ALLOW_UNCALIBRATED_ABSTAIN"):
            self.assertIn(ipucu, metin, ipucu)

    def test_api_reranker_is_also_uncalibrated(self):
        """API skorları 0-1'dir ama BGE'nin sigmoid DAĞILIMI değildir;
        eşiği ölçmeden taşımak kapıyı anlamsız kılar."""
        r = ApiReranker(url="https://ornek/rerank")
        self.assertFalse(r.calibrated_scores)
        with self.assertRaises(RuntimeError):
            check_abstain_compatibility(r, abstain_score=0.30)

    def test_local_reranker_passes(self):
        from src.rerank.reranker import BGEReranker
        check_abstain_compatibility(BGEReranker(), abstain_score=0.30)

    def test_disabled_gate_is_not_blocked(self):
        """Operatör eşiği bilerek kapatmışsa uyumsuzluk diye bir şey yoktur."""
        check_abstain_compatibility(NoOpReranker(), abstain_score=0.0)

    def test_explicit_override_is_honoured(self):
        with mock.patch("src.rerank.provider.ALLOW_UNCALIBRATED", True):
            check_abstain_compatibility(NoOpReranker(), abstain_score=0.30)

    def test_override_is_off_by_default(self):
        self.assertFalse(ALLOW_UNCALIBRATED,
                         "riski kabul bayragi VARSAYILAN olmamali")


class NoOpRerankerTests(unittest.TestCase):
    def test_candidate_order_is_preserved(self):
        r = NoOpReranker()
        out = r.rerank("q", [("a", "x"), ("b", "y"), ("c", "z")])
        self.assertEqual([cid for cid, _ in out], ["a", "b", "c"])

    def test_scores_never_trip_the_relevance_filter(self):
        """Kapalı rerank sessizce bir ELEME kapısına dönüşmemeli: yapay
        skorlar `relevance_min`/`relevance_rel` süzgecini geçmeli."""
        from src.rerank.pipeline import RELEVANCE_MIN, RELEVANCE_REL
        out = NoOpReranker().rerank("q", [(f"c{i}", "t") for i in range(40)])
        tepe = out[0][1]
        esik = max(RELEVANCE_MIN, tepe * RELEVANCE_REL)
        for cid, skor in out:
            self.assertGreaterEqual(skor, esik, cid)

    def test_empty_input(self):
        self.assertEqual(NoOpReranker().rerank("q", []), [])

    def test_top_k_is_respected(self):
        out = NoOpReranker().rerank("q", [("a", "1"), ("b", "2"), ("c", "3")],
                                    top_k=2)
        self.assertEqual(len(out), 2)


class ApiEmbedderTests(unittest.TestCase):
    def _emb(self, **kw):
        return ApiEmbedder(base_url="https://ornek/v1", model="m",
                           api_key="k", **kw)

    def test_vectors_are_l2_normalised(self):
        """İndeks kosinüs varsayıyor; normalize etmemek skorları bozardı."""
        with mock.patch("urllib.request.urlopen",
                        return_value=_http({"data": [{"index": 0,
                                                      "embedding": [3.0, 4.0]}]})):
            v = self._emb(dim=2).embed(["x"])
        self.assertAlmostEqual(float(np.linalg.norm(v[0])), 1.0, places=5)

    def test_order_is_restored_from_index(self):
        """API sırayı bozabilir; `index` alanı yok sayılırsa vektörler
        yanlış chunk'lara bağlanır ve atıflar sessizce kayar."""
        yanit = {"data": [{"index": 1, "embedding": [0.0, 1.0]},
                          {"index": 0, "embedding": [1.0, 0.0]}]}
        with mock.patch("urllib.request.urlopen", return_value=_http(yanit)):
            v = self._emb(dim=2).embed(["ilk", "ikinci"])
        self.assertAlmostEqual(float(v[0][0]), 1.0)
        self.assertAlmostEqual(float(v[1][1]), 1.0)

    def test_sparse_is_reported_as_unsupported(self):
        e = self._emb(dim=2)
        self.assertFalse(e.sparse_supported)
        self.assertEqual(e.embed_sparse(["a", "b"]), [{}, {}])

    def test_warning_names_the_lost_leg(self):
        u = " ".join(embed_warnings(self._emb(dim=2)))
        self.assertIn("SPARSE", u)
        self.assertIn("BM25", u)

    def test_http_error_is_typed(self):
        import urllib.error
        hata = urllib.error.HTTPError("u", 429, "rate", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=hata), \
             mock.patch("src.embed.provider.backoff_delay", return_value=0.0):
            with self.assertRaises(EmbeddingUnavailable):
                self._emb(dim=2).embed(["x"])

    def test_malformed_response_is_typed_not_a_key_error(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_http({"beklenmeyen": 1})):
            with self.assertRaises(EmbeddingUnavailable):
                self._emb(dim=2).embed(["x"])

    def test_empty_input_makes_no_call(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("cagrilmamaliydi")):
            self.assertEqual(self._emb(dim=4).embed([]).shape, (0, 4))

    def test_query_and_passage_use_different_input_type(self):
        """NVIDIA/Cohere'de `input_type` retrieval kalitesini belirgin
        değiştirir; ikisini aynı göndermek sessiz kalite kaybıdır."""
        gonderilen = []

        def _yakala(istek, timeout=None):
            gonderilen.append(json.loads(istek.data))
            return _http({"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

        with mock.patch("urllib.request.urlopen", side_effect=_yakala):
            e = self._emb(dim=2)
            e.embed(["pasaj"])
            e.embed_query("sorgu")
        self.assertEqual(gonderilen[0]["input_type"], "passage")
        self.assertEqual(gonderilen[1]["input_type"], "query")

    def test_batching_splits_large_input(self):
        cagri = {"n": 0}

        def _say(istek, timeout=None):
            g = json.loads(istek.data)
            cagri["n"] += 1
            return _http({"data": [{"index": i, "embedding": [1.0, 0.0]}
                                   for i in range(len(g["input"]))]})

        with mock.patch("urllib.request.urlopen", side_effect=_say):
            self._emb(dim=2, batch_size=2).embed(["a", "b", "c", "d", "e"])
        self.assertEqual(cagri["n"], 3)


class ApiRerankerTests(unittest.TestCase):
    def _rr(self):
        return ApiReranker(url="https://ornek/rerank", model="m", api_key="k")

    def test_index_maps_back_to_chunk_ids(self):
        yanit = {"results": [{"index": 2, "relevance_score": 0.9},
                             {"index": 0, "relevance_score": 0.4}]}
        with mock.patch("urllib.request.urlopen", return_value=_http(yanit)):
            out = self._rr().rerank("q", [("a", "1"), ("b", "2"), ("c", "3")])
        self.assertEqual(out, [("c", 0.9), ("a", 0.4)])

    def test_alternative_score_field(self):
        yanit = {"results": [{"index": 0, "score": 0.7}]}
        with mock.patch("urllib.request.urlopen", return_value=_http(yanit)):
            self.assertEqual(self._rr().rerank("q", [("a", "1")]), [("a", 0.7)])

    def test_unknown_format_raises_instead_of_falling_back(self):
        """Sessizce aday sırasına düşmek, kalite kaybını görünmez kılardı."""
        with mock.patch("urllib.request.urlopen",
                        return_value=_http({"beklenmeyen": []})):
            with self.assertRaises(RerankUnavailable):
                self._rr().rerank("q", [("a", "1")])

    def test_out_of_range_index_is_refused(self):
        yanit = {"results": [{"index": 99, "relevance_score": 0.9}]}
        with mock.patch("urllib.request.urlopen", return_value=_http(yanit)):
            with self.assertRaises(RerankUnavailable):
                self._rr().rerank("q", [("a", "1")])

    def test_empty_input_makes_no_call(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("cagrilmamaliydi")):
            self.assertEqual(self._rr().rerank("q", []), [])

    def test_warning_mentions_recalibration(self):
        u = " ".join(rerank_warnings(self._rr()))
        self.assertIn("KALİBRE DEĞİL", u)


if __name__ == "__main__":
    unittest.main()
