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

from src.embed.provider import (INDEX_DIM, ApiEmbedder, CohereEmbedder,
                                EmbeddingDimensionMismatch,
                                EmbeddingUnavailable, VoyageEmbedder,
                                build_embedder)
from src.embed.provider import provider_warnings as embed_warnings
from src.rerank.provider import (ALLOW_UNCALIBRATED, ApiReranker, NoOpReranker,
                                 RerankUnavailable, build_reranker,
                                 check_abstain_compatibility, top_k_field)
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


class VoyageEmbedderTests(unittest.TestCase):
    """Voyage yolu: taşıma OpenAI biçimi, tek fark `input_type` sözlüğü
    (Voyage `passage`ı 400 ile reddediyor)."""

    def _vo(self, **kw):
        # Taşıma testleri küçük vektörle koşar: beyan tablosunda olmayan ad +
        # açık `expected_dim` (indeks boyutu 1024'ü taklit etmiyoruz).
        kw.setdefault("expected_dim", 2)
        return VoyageEmbedder(base_url="https://api.voyageai.com/v1",
                              model=kw.pop("model", "voyage-test-model"),
                              api_key="k", **kw)

    def _data(self, vektorler):
        return {"object": "list", "data": [{"embedding": v, "index": i}
                                           for i, v in enumerate(vektorler)],
                "model": "voyage-test-model", "usage": {"total_tokens": 3}}

    def test_openai_shaped_endpoint(self):
        """`{base}/embeddings` + `input[]` — OpenAI yoluyla aynı taşıma."""
        gonderilen = []

        def _yakala(istek, timeout=None):
            gonderilen.append((istek.full_url, json.loads(istek.data)))
            return _http(self._data([[1.0, 0.0]]))

        with mock.patch("urllib.request.urlopen", side_effect=_yakala):
            self._vo().embed(["pasaj"])
        url, govde = gonderilen[0]
        self.assertEqual(url, "https://api.voyageai.com/v1/embeddings")
        self.assertEqual(govde["model"], "voyage-test-model")
        self.assertEqual(govde["input"], ["pasaj"])

    def test_passage_maps_to_document_and_query_to_query(self):
        """Voyage `passage`ı REDDEDİYOR (400). Eşleme yapılmazsa indeks
        kurulumunun TAMAMI 400 ile düşer."""
        gonderilen = []

        def _yakala(istek, timeout=None):
            gonderilen.append(json.loads(istek.data)["input_type"])
            return _http(self._data([[1.0, 0.0]]))

        with mock.patch("urllib.request.urlopen", side_effect=_yakala):
            e = self._vo()
            e.embed(["pasaj"])
            e.embed_query("sorgu")
        self.assertEqual(gonderilen, ["document", "query"])

    def test_vectors_are_read_from_data_embedding(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_http(self._data([[3.0, 4.0]]))):
            v = self._vo().embed(["x"])
        self.assertAlmostEqual(float(np.linalg.norm(v[0])), 1.0, places=5)

    def test_declared_model_dimension_is_enforced(self):
        """voyage-multilingual-2 1024 boyutludur (canlı ölçüldü): 512 boyutlu
        model karışıklığı ÖLÇÜMDE değil, beyanla da yakalanır."""
        with mock.patch("urllib.request.urlopen",
                        return_value=_http(self._data([[1.0] * 512]))):
            with self.assertRaises(EmbeddingDimensionMismatch) as ctx:
                VoyageEmbedder(base_url="https://api.voyageai.com/v1",
                               model="voyage-multilingual-2", api_key="k").embed(["x"])
        mesaj = str(ctx.exception)
        self.assertIn("voyage-multilingual-2", mesaj)
        self.assertIn("1024", mesaj)
        self.assertIn("512", mesaj)


class CohereEmbedderTests(unittest.TestCase):
    """Cohere NATIVE yolu (`/v2/embed`) — uyumluluk katmanı input_type'ı
    REDDEDİYOR, o yüzden ayrı istek gövdesi ve ayrı çözümleme var."""

    def _co(self, model="cohere-test-model", **kw):
        # Ölçü testi küçük vektörlerle koşar: beyan tablosunda olmayan bir ad +
        # açık `expected_dim` (indeks boyutu 1024'ü burada taklit etmiyoruz).
        kw.setdefault("expected_dim", 2)
        return CohereEmbedder(base_url="https://api.cohere.com/v2",
                              model=model, api_key="k", **kw)

    def _float(self, vektorler):
        return {"embeddings": {"float": vektorler}}

    def test_native_endpoint_and_request_shape(self):
        """Uç `/embed` ve gövde `texts`+`input_type`+`embedding_types` olmalı:
        OpenAI biçimi (`input`+`/embeddings`) Cohere'in native ucunda 422."""
        gonderilen = []

        def _yakala(istek, timeout=None):
            gonderilen.append((istek.full_url, json.loads(istek.data),
                               dict(istek.headers)))
            return _http(self._float([[1.0, 0.0]]))

        with mock.patch("urllib.request.urlopen", side_effect=_yakala):
            self._co().embed(["pasaj"])
        url, govde, basliklar = gonderilen[0]
        self.assertEqual(url, "https://api.cohere.com/v2/embed")
        self.assertEqual(set(govde), {"model", "texts", "input_type",
                                      "embedding_types"})
        self.assertEqual(govde["texts"], ["pasaj"])
        self.assertEqual(govde["embedding_types"], ["float"])
        self.assertIn("Bearer k", basliklar.get("Authorization", ""))

    def test_float_vectors_are_parsed_in_input_order(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_http(self._float([[1.0, 0.0], [0.0, 1.0]]))):
            v = self._co().embed(["ilk", "ikinci"])
        self.assertAlmostEqual(float(v[0][0]), 1.0)
        self.assertAlmostEqual(float(v[1][1]), 1.0)
        self.assertAlmostEqual(float(np.linalg.norm(v[0])), 1.0, places=5)

    def test_query_and_document_are_mapped_to_cohere_vocabulary(self):
        """v3 modellerinde sorgu/pasaj ayrımı retrieval kalitesini belirler;
        ikisini aynı göndermek sessiz kalite kaybıdır."""
        gonderilen = []

        def _yakala(istek, timeout=None):
            gonderilen.append(json.loads(istek.data)["input_type"])
            return _http(self._float([[1.0, 0.0]]))

        with mock.patch("urllib.request.urlopen", side_effect=_yakala):
            e = self._co()
            e.embed(["pasaj"])
            e.embed_query("sorgu")
        self.assertEqual(gonderilen, ["search_document", "search_query"])

    def test_transient_in_body_error_is_retried(self):
        """2xx gövdesinde geçici sağlayıcı hatası (yük altında görüldü):
        yeniden denenmeli, başarıyla bitmeli."""
        yanitlar = [{"error": {"code": 503, "message": "overloaded"}},
                    self._float([[1.0, 0.0]])]
        cagri = {"n": 0}

        def _say(istek, timeout=None):
            cagri["n"] += 1
            return _http(yanitlar[min(cagri["n"], 2) - 1])

        with mock.patch("urllib.request.urlopen", side_effect=_say), \
             mock.patch("src.embed.provider.backoff_delay", return_value=0.0):
            v = self._co().embed(["x"])
        self.assertEqual(cagri["n"], 2)
        self.assertAlmostEqual(float(v[0][0]), 1.0)

    def test_terminal_in_body_error_fails_with_provider_message(self):
        cagri = {"n": 0}

        def _say(istek, timeout=None):
            cagri["n"] += 1
            return _http({"error": {"code": 401, "message": "invalid api token"}})

        with mock.patch("urllib.request.urlopen", side_effect=_say), \
             mock.patch("src.embed.provider.backoff_delay", return_value=0.0):
            with self.assertRaises(EmbeddingUnavailable) as ctx:
                self._co().embed(["x"])
        self.assertEqual(cagri["n"], 1, "kalıcı hata İLK denemede bitmeli")
        self.assertIn("invalid api token", str(ctx.exception))

    def test_missing_float_block_is_named_not_a_key_error(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_http({"embeddings": {}})):
            with self.assertRaises(EmbeddingUnavailable) as ctx:
                self._co().embed(["x"])
        self.assertIn("embeddings.float", str(ctx.exception))

    def test_batching_still_splits_the_native_call(self):
        cagri = {"n": 0}

        def _say(istek, timeout=None):
            g = json.loads(istek.data)
            cagri["n"] += 1
            return _http(self._float([[1.0, 0.0]] * len(g["texts"])))

        with mock.patch("urllib.request.urlopen", side_effect=_say):
            self._co(batch_size=2).embed(["a", "b", "c", "d", "e"])
        self.assertEqual(cagri["n"], 3)

    def test_empty_input_makes_no_call(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("cagrilmamaliydi")):
            self.assertEqual(self._co().embed([]).shape, (0, 2))


class CohereDimensionInvariantTests(unittest.TestCase):
    """BOYUT DEĞİŞMEZİ: farklı model = farklı boyut; karışık indeks sessizce
    bozuk arama üretir. İlk gömme, hiçbir sorgu koşmadan, ADIYLA reddedilir."""

    def _co(self, model, **kw):
        return CohereEmbedder(base_url="https://api.cohere.com/v2", model=model,
                              api_key="k", **kw)

    def _vektorler(self, genislik):
        return {"embeddings": {"float": [[1.0] * genislik]}}

    def test_declared_light_model_is_refused_before_indexing(self):
        """`embed-multilingual-light-v3.0` 384 boyutludur; 1024 uçla
        eşleşmişse (uç karışıklığı) bu ADIYLA söylenmeli."""
        with mock.patch("urllib.request.urlopen",
                        return_value=_http(self._vektorler(1024))):
            with self.assertRaises(EmbeddingDimensionMismatch) as ctx:
                self._co("embed-multilingual-light-v3.0").embed(["x"])
        mesaj = str(ctx.exception)
        self.assertIn("embed-multilingual-light-v3.0", mesaj)
        self.assertIn("384", mesaj)
        self.assertIn("1024", mesaj)

    def test_dimension_different_from_index_dimension_is_refused(self):
        """Beyan tablosunda olmayan bir modelde bile ÖLÇÜLEN boyut indeksin
        boyutundan farklıysa reddedilir (ör. uç başka varyanta düşürülmüş)."""
        with mock.patch("urllib.request.urlopen",
                        return_value=_http(self._vektorler(384))):
            with self.assertRaises(EmbeddingDimensionMismatch) as ctx:
                self._co("bilinmeyen-gomme-modeli").embed(["x"])
        mesaj = str(ctx.exception)
        self.assertIn("bilinmeyen-gomme-modeli", mesaj)
        self.assertIn("384", mesaj)
        self.assertIn(f"indeks={INDEX_DIM}", mesaj)

    def test_matching_dimension_passes(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_http(self._vektorler(INDEX_DIM))):
            v = self._co("bilinmeyen-gomme-modeli").embed(["x"])
        self.assertEqual(v.shape, (1, INDEX_DIM))

    def test_mismatch_is_a_kind_of_unavailable(self):
        """Çağıranlar `EmbeddingUnavailable` yakalıyor; yeni tip onun ALT
        tipi olmalı ki sessizce kaçmasın."""
        self.assertTrue(issubclass(EmbeddingDimensionMismatch,
                                   EmbeddingUnavailable))


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

    def test_cohere_provider_builds_the_native_client(self):
        e = build_embedder(provider="cohere", base_url="https://api.cohere.com/v2",
                           model="embed-multilingual-v3.0", api_key="k")
        self.assertIsInstance(e, CohereEmbedder)
        self.assertFalse(e.sparse_supported)

    def test_voyage_provider_builds_the_openai_shaped_client(self):
        e = build_embedder(provider="voyage",
                           base_url="https://api.voyageai.com/v1",
                           model="voyage-multilingual-2", api_key="k")
        self.assertIsInstance(e, VoyageEmbedder)
        self.assertEqual(e._input_type("passage"), "document")

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

    def test_voyage_data_key_is_accepted(self):
        """Voyage `data[]` döndürür (Cohere `results[]`); ayrım SAĞLAYICI
        gerçeği, kozmetik değil — eski kod bu biçimi tanımayıp istisna atardı."""
        yanit = {"object": "list",
                 "data": [{"relevance_score": 0.9, "index": 2},
                          {"relevance_score": 0.4, "index": 0}]}
        with mock.patch("urllib.request.urlopen", return_value=_http(yanit)):
            out = ApiReranker(url="https://api.voyageai.com/v1/rerank",
                              model="rerank-3", api_key="k").rerank(
                                  "q", [("a", "1"), ("b", "2"), ("c", "3")])
        self.assertEqual(out, [("c", 0.9), ("a", 0.4)])

    def test_neither_results_nor_data_is_still_a_loud_error(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_http({"sonuclar": []})):
            with self.assertRaises(RerankUnavailable) as ctx:
                self._rr().rerank("q", [("a", "1")])
        self.assertIn("ne results ne data", str(ctx.exception))

    def test_top_k_field_matches_the_provider(self):
        """Cohere `top_n` bekler (top_k → 422), Voyage `top_k` (top_n → 400);
        yanlış ad isteği TAMAMEN düşürür (ölçüldü 2026-09-17)."""
        self.assertEqual(top_k_field("https://api.voyageai.com/v1/rerank"),
                         "top_k")
        self.assertEqual(top_k_field("https://api.cohere.com/v2/rerank"),
                         "top_n")
        self.assertEqual(top_k_field("https://api.cohere.com/v2/rerank",
                                     override="top_k"), "top_k")

    def test_top_k_limit_uses_the_resolved_field_name(self):
        gonderilen = []

        def _yakala(istek, timeout=None):
            gonderilen.append(json.loads(istek.data))
            return _http({"data": [{"index": 0, "relevance_score": 0.5}]})

        with mock.patch("urllib.request.urlopen", side_effect=_yakala):
            ApiReranker(url="https://api.voyageai.com/v1/rerank", model="rerank-3",
                        api_key="k").rerank("q", [("a", "1")], top_k=1)
            ApiReranker(url="https://api.cohere.com/v2/rerank",
                        model="rerank-multilingual-v3.0",
                        api_key="k").rerank("q", [("a", "1")], top_k=1)
        self.assertEqual(gonderilen[0].get("top_k"), 1)
        self.assertNotIn("top_n", gonderilen[0])
        self.assertEqual(gonderilen[1].get("top_n"), 1)
        self.assertNotIn("top_k", gonderilen[1])

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
