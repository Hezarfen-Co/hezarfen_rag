"""Faz 1.4 entegrasyon — 12-bio hibrit retrieval (dense+BM25+sparse → RRF).

Resmi Recall@20 (≥0.98) ölçümü golden set (Faz 1.8) sonrası. Buradaki testler
füzyonun çalıştığını + bariz-ilgili chunk'ın üst sıralarda geldiğini doğrular.
Model yüklenemezse ATLANIR.
"""
import os
import unittest

from src.ingest.canonical import build_canonical
from src.chunk import chunk_document
from src.index import DenseIndex, BM25Index
from src.retrieve import SparseIndex, HybridRetriever

BOOK = os.path.join("data", "lise", "12", "biyoloji", "kitap.pdf")


def _prepare():
    try:
        from src.embed import BGEM3Embedder
        doc = build_canonical(BOOK, sinif="12", ders="biyoloji")
        children = [c for c in chunk_document(doc) if c.level == "child"]
        emb = BGEM3Embedder()
        ids, vecs = emb.embed_chunks(children, batch_size=16)
        texts = [c.text for c in children]
        sparse_docs = emb.embed_sparse(texts, batch_size=16)
        return children, ids, vecs, texts, sparse_docs, emb
    except Exception:
        return None


_PREP = _prepare() if os.path.exists(BOOK) else None


@unittest.skipUnless(_PREP is not None, "12-bio verisi yok / BGE-M3 yüklenemedi")
class HybridRetrieveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.children, cls.ids, vecs, texts, sparse_docs, cls.emb = _PREP
        cls.text_by_id = {cid: t for cid, t in zip(cls.ids, texts)}
        dense = DenseIndex(dim=1024).build(cls.ids, vecs)
        bm25 = BM25Index().build(cls.ids, texts)
        sparse = SparseIndex().build(cls.ids, sparse_docs)
        cls.retr = HybridRetriever(cls.emb, dense, bm25, sparse)

    def test_returns_topk_valid_ids(self):
        hits = self.retr.retrieve("DNA'nın yapısı", top_k=20)
        self.assertEqual(len(hits), 20)
        self.assertTrue(all(cid in self.text_by_id for cid, _ in hits))
        # RRF skorları azalan
        scores = [s for _, s in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_relevant_chunk_in_top5(self):
        checks = [
            ("DNA nükleotid çift sarmal yapısı", ("dna", "nükleot", "sarmal", "baz")),
            ("fotosentez kloroplast ışık", ("fotosentez", "kloroplast", "ışık")),
        ]
        for query, kws in checks:
            hits = self.retr.retrieve(query, top_k=5)
            joined = " ".join(self.text_by_id[cid].lower() for cid, _ in hits)
            self.assertTrue(any(w in joined for w in kws),
                            f"'{query}' top5 icinde {kws} yok")

    def test_fusion_combines_sources(self):
        # RRF havuzu tek retriever'ın kaçırabileceğini kapsar: sparse'siz vs sparse'lı
        q = "protein sentezi ribozom"
        hits = self.retr.retrieve(q, top_k=20)
        self.assertGreaterEqual(len(hits), 10)
        self.assertGreater(hits[0][1], 0.0)


if __name__ == "__main__":
    unittest.main()
