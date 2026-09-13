"""Faz 1.5 birim testleri — rerank_select çeşitlilik + parent genişletme (stub reranker)."""
import unittest
from dataclasses import dataclass, field

from src.rerank import rerank_select


@dataclass
class _Chunk:
    chunk_id: str
    text: str
    parent_id: str | None = None
    span_ids: list = field(default_factory=list)


class _StubReranker:
    """Skor = sorgu kelimelerinin metinde geçme sayısı (model yok).

    `skorlar` verilirse o sabit tablo kullanılır — belirli skor sıralamalarını
    (örn. #59'un 0,98 / 0,94 / 0,90… kurgusu) birebir kurmak için."""

    def __init__(self, skorlar: dict | None = None):
        self.skorlar = skorlar

    def rerank(self, query, items, top_k=None, normalize=True):
        if self.skorlar is not None:
            scored = [(cid, float(self.skorlar.get(cid, 0.0))) for cid, _ in items]
        else:
            qs = set(query.lower().split())
            scored = [(cid, float(sum(t.lower().count(w) for w in qs)))
                      for cid, t in items]
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k] if top_k else scored


def _corpus():
    chunks = {
        "c1": _Chunk("c1", "DNA nükleotid", "P1", ["s1"]),
        "c2": _Chunk("c2", "DNA baz çifti", "P1", ["s2"]),
        "c3": _Chunk("c3", "fotosentez ışık", "P2", ["s3"]),
        "c4": _Chunk("c4", "kloroplast pigment", "P2", ["s4"]),
        "P1": _Chunk("P1", "DNA bölümü tüm metin", None, ["s1", "s2"]),
        "P2": _Chunk("P2", "fotosentez bölümü tüm metin", None, ["s3", "s4"]),
    }
    hits = [("c1", 0.9), ("c2", 0.8), ("c3", 0.7), ("c4", 0.6)]
    return chunks, hits


class RerankSelectTests(unittest.TestCase):
    def test_diversity_still_applies_to_reserved_slots(self):
        """SÖZLEŞME DEĞİŞTİ (#59, 2026-09-12).

        Eski hâli `diversity_share=1.0`'a denk geliyordu: kısıt HER yuvada
        uygulanıyor ve aynı parent'taki ikinci kanıt — skoru ne olursa olsun —
        eleniyordu. Artık kısıt yalnız **ayrılmış** yuvalarda geçerli; bu test
        o davranışı açıkça `diversity_share=1.0` ile sınar."""
        chunks, hits = _corpus()
        res = rerank_select("DNA", hits, chunks, _StubReranker(),
                            top_n=2, per_parent=1, diversity_share=1.0)
        ids = [r.chunk_id for r in res]
        self.assertIn("c1", ids)
        self.assertNotIn("c2", ids)          # aynı parent → dolgu aşaması eler
        # DİKKAT: eski test burada `len(ids) == 2` bekliyordu. Artık ikinci yuva
        # BOŞ kalıyor çünkü "DNA" sorgusunda c3/c4'ün skoru 0 ve ilgililik
        # tabanını geçmiyor. `top_n` bir kota değil ÜST SINIR: alakasızla
        # doldurmak bağlamı sulandırır ve token maliyeti ekler.
        self.assertLessEqual(len(ids), 2)
        self.assertTrue(all(chunks[i].parent_id == "P1" for i in ids))

    def test_parent_expansion(self):
        chunks, hits = _corpus()
        res = rerank_select("DNA", hits, chunks, _StubReranker(), top_n=1)
        self.assertEqual(res[0].chunk_id, "c1")
        self.assertEqual(res[0].parent_id, "P1")
        self.assertEqual(res[0].parent_text, "DNA bölümü tüm metin")
        self.assertEqual(res[0].span_ids, ["s1"])   # atıf child span'ında

    def test_no_parent_expansion_flag(self):
        chunks, hits = _corpus()
        res = rerank_select("DNA", hits, chunks, _StubReranker(),
                            top_n=1, expand_parents=False)
        self.assertIsNone(res[0].parent_text)

    def test_same_parent_chunks_fill_when_relevant(self):
        """SÖZLEŞME DEĞİŞTİ (#59, 2026-09-12).

        Eski test `len(res) == 3` bekliyordu: kod yuvaları doldurmak için son
        çare olarak kısıtı gevşetip skoru ~0 olan chunk'ları da alıyordu.
        `top_n` artık bir KOTA değil ÜST SINIR: alakasızla doldurmak bağlamı
        sulandırır, token maliyetini artırır ve modele "bu da kaynak" der.
        Ölçüldü: skor dağılımı iki kutuplu (medyan 0,006 / p90 0,619), yani
        eşiğin altı gerçekten alakasızdır.

        Burada "DNA" sorgusunda c1 ve c2 ilgili (ikisi de P1), c3/c4 skoru 0 →
        ilgili olan ikisi alınır, üçüncü yuva BOŞ kalır."""
        chunks, hits = _corpus()
        res = rerank_select("DNA", hits, chunks, _StubReranker(),
                            top_n=3, per_parent=1)
        ids = [r.chunk_id for r in res]
        self.assertIn("c1", ids)
        self.assertIn("c2", ids)         # aynı parent, İLGİLİ → artık alınır
        self.assertLessEqual(len(res), 3)
        self.assertTrue(all(chunks[i].parent_id == "P1" for i in ids))

    def test_candidate_n_limits_pool(self):
        chunks, hits = _corpus()
        res = rerank_select("fotosentez", hits, chunks, _StubReranker(),
                            top_n=5, candidate_n=2)      # yalnız c1,c2 havuzda
        ids = {r.chunk_id for r in res}
        self.assertTrue(ids <= {"c1", "c2"})             # c3/c4 havuz dışı


class DiversityRegressionTests(unittest.TestCase):
    """#59 (EXP-010/ACC-06) — çeşitlilik kısıtı ikinci gerçek kanıtı düşürüyordu.

    Denetimde koşulan senaryo (4 aday: a1,a2 AYNI parent=gold; b1,b2 alakasız):
      `top_n=2` → `['a1','b1']`, gold kapsama 1/2, **recall 0,5**
      `top_n=6`, 6 farklı parent varken → `['a1','b1','b2','b3','b4','b5']`;
      ikinci gold span (rerank skoru 0,94 — 2. EN İYİ) **tamamen kayboldu**,
      yerine 0,89–0,85 skorlu alakasız chunk'lar geldi.

    Yaygınlık: golden set'te 133 cevaplanabilir item'in **70'i çok-span'lı**
    (44× 2-span, 16× 3-span, 8× ≥4-span) → kural, istisna değil.
    """

    @staticmethod
    def _kurgu(n_alakasiz=5):
        """a1,a2 aynı parent (gold); b1..bN ayrı parent'larda, daha düşük skorlu."""
        chunks = {
            "a1": _Chunk("a1", "gold bir", "PA", ["sa1"]),
            "a2": _Chunk("a2", "gold iki", "PA", ["sa2"]),
            "PA": _Chunk("PA", "gold parent", None, ["sa1", "sa2"]),
        }
        skor = {"a1": 0.98, "a2": 0.94}
        for i in range(1, n_alakasiz + 1):
            cid, pid = f"b{i}", f"PB{i}"
            chunks[cid] = _Chunk(cid, f"alakasiz {i}", pid, [f"sb{i}"])
            chunks[pid] = _Chunk(pid, f"alakasiz parent {i}", None, [f"sb{i}"])
            skor[cid] = 0.90 - i * 0.01
        hits = [(c, 1.0) for c in skor]
        return chunks, hits, _StubReranker(skor)

    def test_second_gold_survives_with_two_slots(self):
        """Denetimin birinci senaryosu: top_n=2 → eskiden ['a1','b1']."""
        chunks, hits, rr = self._kurgu()
        ids = [r.chunk_id for r in rerank_select("q", hits, chunks, rr, top_n=2)]
        self.assertIn("a1", ids)
        self.assertIn("a2", ids, "ikinci gold kanıt yine düştü")

    def test_second_gold_survives_with_many_distinct_parents(self):
        """Denetimin ikinci senaryosu: 6 farklı parent varken bile ikinci gold
        span kaybolmamalı (0,94 skor, 2. en iyi)."""
        chunks, hits, rr = self._kurgu(n_alakasiz=5)
        ids = [r.chunk_id for r in rerank_select("q", hits, chunks, rr, top_n=6)]
        self.assertIn("a1", ids)
        self.assertIn("a2", ids)

    def test_all_evidence_recall_is_now_one(self):
        chunks, hits, rr = self._kurgu()
        for top_n in (2, 3, 6):
            with self.subTest(top_n=top_n):
                ids = set(r.chunk_id for r in
                          rerank_select("q", hits, chunks, rr, top_n=top_n))
                self.assertEqual(len({"a1", "a2"} & ids), 2)

    @staticmethod
    def _tek_parent(ikincil_skor):
        """Bir parent'ta 10 chunk + 3 ayrı parent'ta birer chunk."""
        chunks = {"P": _Chunk("P", "parent", None, [])}
        skor = {}
        for i in range(10):
            cid = f"x{i}"
            chunks[cid] = _Chunk(cid, f"ayni parent {i}", "P", [f"sx{i}"])
            skor[cid] = 0.99 if i == 0 else ikincil_skor
        for i in range(3):
            cid, pid = f"y{i}", f"PY{i}"
            chunks[cid] = _Chunk(cid, f"baska {i}", pid, [f"sy{i}"])
            chunks[pid] = _Chunk(pid, f"baska parent {i}", None, [f"sy{i}"])
            skor[cid] = 0.40 - i * 0.01
        return chunks, [(c, 1.0) for c in skor], _StubReranker(skor)

    def test_many_evidences_from_one_parent_are_allowed_when_relevant(self):
        """KARAR (Kadir, 2026-09-12): "birden fazla kanıt getirebilir, 2'den de
        fazla olabilir, konuyla ilgiliyse". Aynı parent'tan 3-5 chunk gelmesi
        bir kusur DEĞİL, çok-span'lı cevabın gereğidir.

        Eski test bunun tersini savunuyordu ("tek parent bütün yuvaları
        alamaz") — o kural yapısaldı ve ölçümde `all_evidence_recall`'ı
        0,000'a düşürüyordu."""
        chunks, hits, rr = self._tek_parent(ikincil_skor=0.80)   # hepsi İLGİLİ
        res = rerank_select("q", hits, chunks, rr, top_n=6)
        ayni = sum(1 for r in res if chunks[r.chunk_id].parent_id == "P")
        self.assertGreaterEqual(ayni, 5, "ilgili kanıtlar yine elendi")

    def test_irrelevant_same_parent_chunks_are_rejected(self):
        """Asıl koruma ilgililik eşiği: eşiğin ALTINDAki aynı-parent chunk'lar
        alınmaz, yuvalar çeşitli dolguya gider."""
        chunks, hits, rr = self._tek_parent(ikincil_skor=0.001)  # ilgisiz
        res = rerank_select("q", hits, chunks, rr, top_n=6)
        ayni = sum(1 for r in res if chunks[r.chunk_id].parent_id == "P")
        self.assertEqual(ayni, 1, "ilgisiz aynı-parent chunk'lar alındı")
        parents = {chunks[r.chunk_id].parent_id for r in res}
        self.assertGreater(len(parents), 1)

    def test_relevance_threshold_is_relative_to_the_top_score(self):
        """Tepe skor sorguya göre 0,0025–0,9999 arasında değişiyor; sabit eşik
        kolay sorguda çok şey alır, zor sorguda hiçbir şey."""
        chunks = {"P1": _Chunk("P1", "p", None, []), "P2": _Chunk("P2", "p", None, [])}
        # tepe 0,40 -> esik = max(0.05, 0.04) = 0.05
        skor = {"a": 0.40, "b": 0.20, "c": 0.01}
        for cid, pid in (("a", "P1"), ("b", "P1"), ("c", "P2")):
            chunks[cid] = _Chunk(cid, cid, pid, [cid])
        hits = [(c, 1.0) for c in skor]
        res = rerank_select("q", hits, chunks, _StubReranker(skor), top_n=2)
        self.assertEqual([r.chunk_id for r in res], ["a", "b"])

    def test_share_zero_is_pure_score_order(self):
        chunks, hits, rr = self._kurgu()
        ids = [r.chunk_id for r in rerank_select("q", hits, chunks, rr, top_n=3,
                                                 diversity_share=0.0)]
        self.assertEqual(ids[:2], ["a1", "a2"])

    def test_share_one_reproduces_the_old_loss(self):
        """Eski davranışın kaybı GERÇEKTEN oluyordu — kayda geçir."""
        chunks, hits, rr = self._kurgu()
        ids = [r.chunk_id for r in rerank_select("q", hits, chunks, rr, top_n=2,
                                                 diversity_share=1.0)]
        self.assertNotIn("a2", ids)

    def test_env_default_is_read_once(self):
        """DİKKAT — geri yükleme `with` BLOĞUNUN DIŞINDA olmalı.

        İlk yazımda `finally: importlib.reload(...)` bloğun İÇİNDEYDİ; env
        hâlâ yamalı olduğu için reload değeri 0.0'a GERİ ALMIYOR, tersine
        yeniden 0.0 yapıyordu. Sızıntı sonraki testi düşürdü
        (`test_one_parent_cannot_take_every_slot`, alfabetik olarak sonra
        koşuyor). Aynı tuzağa bu depoda ikinci kez düşüldü — kayda geçirildi."""
        import importlib
        from unittest import mock
        from src.rerank import pipeline
        try:
            with mock.patch.dict("os.environ", {"RAG_DIVERSITY_SHARE": "0"}):
                m = importlib.reload(pipeline)
                self.assertEqual(m.DIVERSITY_SHARE_DEFAULT, 0.0)
        finally:
            importlib.reload(pipeline)          # env TEMİZ hâldeyken
        # Varsayılan 0.0: çeşitlilik artık YALNIZ DOLGU, birincil ölçüt
        # ilgililik eşiği (#59 kararı).
        self.assertEqual(pipeline.DIVERSITY_SHARE_DEFAULT, 0.0)
        self.assertEqual(pipeline.RELEVANCE_MIN, 0.05)
        self.assertEqual(pipeline.RELEVANCE_REL, 0.10)

    def test_share_is_clamped(self):
        chunks, hits, rr = self._kurgu()
        for share in (-5.0, 9.0):
            with self.subTest(share=share):
                res = rerank_select("q", hits, chunks, rr, top_n=3,
                                    diversity_share=share)
                self.assertEqual(len(res), 3)

    def test_no_duplicates_across_stages(self):
        chunks, hits, rr = self._kurgu()
        ids = [r.chunk_id for r in rerank_select("q", hits, chunks, rr, top_n=6)]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()


class MaxLengthConfigTests(unittest.TestCase):
    """#96 (EXP-018) — kırpma uzunluğu CPU gecikmesini belirliyor.

    ÖLÇÜLDÜ (bu makine, 3 sorgu ortalaması): 40 adayda max_length 512 → 95,9 s,
    192 → 37,2 s. 8 adayda 192 → 6,1 s. Kapı O-05 uçtan uca p50 ≤ 6 s istiyor;
    en agresif ayar TEK BAŞINA bütün bütçeyi yiyor.
    """

    def test_default_is_unchanged(self):
        """Kısaltmanın KALİTE bedeli mevcut golden set ile ölçülemiyor
        (sorgular birimlerin kendi metni → ölçüm cross-encoder'in aleyhine).
        Ölçmeden varsayılanı oynatmak sessiz bir kalite kaybı olurdu."""
        from src.rerank.reranker import MAX_LENGTH_DEFAULT, BGEReranker
        self.assertEqual(MAX_LENGTH_DEFAULT, 512)
        self.assertEqual(BGEReranker().max_length, 512)

    def test_env_overrides(self):
        import os
        from unittest import mock

        from src.rerank.reranker import _env_max_length
        with mock.patch.dict(os.environ, {"RAG_RERANK_MAX_LENGTH": "192"}):
            self.assertEqual(_env_max_length(), 192)

    def test_explicit_argument_wins(self):
        from src.rerank.reranker import BGEReranker
        self.assertEqual(BGEReranker(max_length=256).max_length, 256)

    def test_broken_env_falls_back(self):
        import os
        from unittest import mock

        from src.rerank.reranker import _env_max_length
        for bozuk in ("", "uzun", "512.5", "None"):
            with self.subTest(bozuk=bozuk):
                with mock.patch.dict(os.environ,
                                     {"RAG_RERANK_MAX_LENGTH": bozuk}):
                    self.assertEqual(_env_max_length(), 512)

    def test_absurd_values_are_refused(self):
        """8 token'lık bir pasaj anlamsızdır; 100000 modelin sınırını aşar ve
        çalışma anında patlar — açılışta sessizce kabul edilmemeli."""
        import os
        from unittest import mock

        from src.rerank.reranker import _env_max_length
        for disarida in ("8", "0", "-512", "100000"):
            with self.subTest(deger=disarida):
                with mock.patch.dict(os.environ,
                                     {"RAG_RERANK_MAX_LENGTH": disarida}):
                    self.assertEqual(_env_max_length(), 512)
