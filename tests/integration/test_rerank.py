"""Faz 1.5 entegrasyon — 12-bio üzerinde gerçek BGE-reranker-v2-m3.

Resmi nDCG@10 (≥0.90) + rerank kazancı golden set (Faz 1.8) sonrası. Buradaki
testler reranker'ın çalıştığını + bariz-ilgili chunk'ı üste çektiğini +
çeşitlilik/parent genişletmeyi gerçek veride doğrular. Model yoksa ATLANIR.
"""
import os
import unittest

from src.ingest.canonical import build_canonical
from src.chunk import chunk_document
from src.index import DenseIndex, BM25Index
from src.retrieve import SparseIndex, HybridRetriever
from src.rerank import BGEReranker, rerank_select

BOOK = os.path.join("data", "lise", "12", "biyoloji", "kitap.pdf")


def _prepare():
    try:
        from src.embed import BGEM3Embedder
        doc = build_canonical(BOOK, sinif="12", ders="biyoloji")
        chunks = chunk_document(doc)
        children = [c for c in chunks if c.level == "child"]
        chunks_by_id = {c.chunk_id: c for c in chunks}      # child + parent
        emb = BGEM3Embedder()
        ids, vecs = emb.embed_chunks(children, batch_size=16)
        texts = [c.text for c in children]
        sparse_docs = emb.embed_sparse(texts, batch_size=16)
        dense = DenseIndex(dim=1024).build(ids, vecs)
        bm25 = BM25Index().build(ids, texts)
        sparse = SparseIndex().build(ids, sparse_docs)
        retr = HybridRetriever(emb, dense, bm25, sparse)
        rr = BGEReranker()
        rr.rerank("ısınma", [("x", "deneme metni")])         # modeli yükle
        return chunks_by_id, retr, rr
    except Exception:
        return None


_PREP = _prepare() if os.path.exists(BOOK) else None


@unittest.skipUnless(_PREP is not None, "12-bio yok / BGE modelleri yüklenemedi")
class RerankIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks_by_id, cls.retr, cls.rr = _PREP

    def test_rerank_scores_sorted(self):
        hits = self.retr.retrieve("DNA nükleotid yapısı", top_k=20)
        items = [(cid, self.chunks_by_id[cid].text) for cid, _ in hits]
        ranked = self.rr.rerank("DNA nükleotid yapısı", items)
        scores = [s for _, s in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(len(ranked), len(items))

    def test_rerank_select_topn_and_parent(self):
        hits = self.retr.retrieve("DNA nükleotid çift sarmal", top_k=40)
        res = rerank_select("DNA nükleotid çift sarmal", hits, self.chunks_by_id,
                            self.rr, top_n=8, candidate_n=40, per_parent=1)
        self.assertLessEqual(len(res), 8)
        self.assertGreater(len(res), 0)
        # en az bir sonuçta parent genişletme (child'ın parent'ı varsa)
        self.assertTrue(any(r.parent_text for r in res if r.parent_id))
        # çeşitlilik: seçilen chunk'ların parent'ları benzersiz (per_parent=1)
        pids = [r.parent_id for r in res if r.parent_id]
        self.assertEqual(len(pids), len(set(pids)))

    def test_top1_is_relevant(self):
        hits = self.retr.retrieve("fotosentez ışık reaksiyonu kloroplast", top_k=40)
        res = rerank_select("fotosentez ışık reaksiyonu kloroplast", hits,
                            self.chunks_by_id, self.rr, top_n=5)
        top_txt = res[0].text.lower()
        self.assertTrue(any(w in top_txt for w in
                            ("fotosentez", "kloroplast", "ışık", "klorofil")))


if __name__ == "__main__":
    unittest.main()
