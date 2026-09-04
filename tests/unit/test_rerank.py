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
    """Skor = sorgu kelimelerinin metinde geçme sayısı (model yok)."""
    def rerank(self, query, items, top_k=None, normalize=True):
        qs = set(query.lower().split())
        scored = [(cid, float(sum(t.lower().count(w) for w in qs))) for cid, t in items]
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
    def test_diversity_one_per_parent(self):
        chunks, hits = _corpus()
        res = rerank_select("DNA", hits, chunks, _StubReranker(),
                            top_n=2, per_parent=1)
        ids = [r.chunk_id for r in res]
        self.assertEqual(len(ids), 2)
        self.assertIn("c1", ids)                 # en yüksek DNA skoru
        self.assertNotIn("c2", ids)              # aynı parent (P1) → çeşitlilik eledi
        parents = {chunks[i].parent_id for i in ids}
        self.assertEqual(len(parents), 2)        # farklı parent'lar (P1, P2)

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


if __name__ == "__main__":
    unittest.main()
