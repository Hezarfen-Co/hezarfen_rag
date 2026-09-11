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
        self.assertEqual(len(ids), 2)
        self.assertIn("c1", ids)
        self.assertNotIn("c2", ids)
        self.assertEqual(len({chunks[i].parent_id for i in ids}), 2)

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

    def test_fallback_fills_when_diversity_short(self):
        # per_parent=1, ama top_n=3 ve yalnız 2 parent var → fallback c2'yi ekler
        chunks, hits = _corpus()
        res = rerank_select("DNA", hits, chunks, _StubReranker(),
                            top_n=3, per_parent=1)
        self.assertEqual(len(res), 3)
        self.assertIn("c2", [r.chunk_id for r in res])   # gevşetilmiş kısıt

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

    def test_one_parent_cannot_take_every_slot(self):
        """Kısıtı tümden kaldırmadık: ayrılmış yuvalar yeni parent'lara aittir.

        Tek bir parent'ta 10 yüksek skorlu chunk varsa hepsini alsaydı bağlam
        tek bir bölüme hapsolur, konu çeşitliliği ölürdü."""
        chunks = {"P": _Chunk("P", "parent", None, [])}
        skor = {}
        for i in range(10):
            cid = f"x{i}"
            chunks[cid] = _Chunk(cid, f"ayni parent {i}", "P", [f"sx{i}"])
            skor[cid] = 0.99 - i * 0.001
        for i in range(3):
            cid, pid = f"y{i}", f"PY{i}"
            chunks[cid] = _Chunk(cid, f"baska {i}", pid, [f"sy{i}"])
            chunks[pid] = _Chunk(pid, f"baska parent {i}", None, [f"sy{i}"])
            skor[cid] = 0.50 - i * 0.01
        hits = [(c, 1.0) for c in skor]
        res = rerank_select("q", hits, chunks, _StubReranker(skor), top_n=6)
        parents = {chunks[r.chunk_id].parent_id for r in res}
        self.assertGreater(len(parents), 1, "tek parent bütün yuvaları aldı")

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
        self.assertEqual(pipeline.DIVERSITY_SHARE_DEFAULT, 0.5)

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
