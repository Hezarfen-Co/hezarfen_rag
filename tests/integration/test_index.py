"""Faz 1.3 entegrasyon testi — 12-bio gerçek vektörlerde Dense (Qdrant) + BM25.

Kabul (plan 1.3): ANN recall ≥ 0.995 (exact'e karşı). Model yüklenemezse ATLANIR.
"""
import os
import unittest

import corpus

import numpy as np

from src.ingest.canonical import build_canonical
from src.chunk import chunk_document
from src.index import DenseIndex, exact_topk, BM25Index

BOOK = corpus.book_path()


def _prepare():
    try:
        from src.embed import BGEM3Embedder
        doc = build_canonical(BOOK, sinif=corpus.find_book()[1], ders=corpus.find_book()[2])
        chunks = chunk_document(doc)
        children = [c for c in chunks if c.level == "child"]
        emb = corpus.shared_embedder()
        ids, vecs = emb.embed_chunks(children, batch_size=16)
        return children, ids, vecs, emb
    except Exception:
        return None


_PREP = _prepare() if os.path.exists(BOOK) else None


@unittest.skipUnless(_PREP is not None, "12-bio verisi yok / BGE-M3 yüklenemedi")
class DenseBM25IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.children, cls.ids, cls.vecs, cls.emb = _PREP
        cls.texts = [c.text for c in cls.children]
        cls.dense = DenseIndex(dim=1024).build(cls.ids, cls.vecs)
        cls.bm25 = BM25Index().build(cls.ids, cls.texts)

    def test_index_sizes(self):
        self.assertEqual(len(self.dense), len(self.ids))
        self.assertEqual(len(self.bm25), len(self.ids))
        self.assertGreater(len(self.ids), 100)             # 12-bio ~258

    def test_ann_recall_vs_exact(self):
        k = 20
        recalls = []
        for qi in range(0, len(self.vecs), 10):            # ~26 sorgu
            q = self.vecs[qi]
            ann = {cid for cid, _ in self.dense.search(q, top_k=k)}
            exact = {cid for cid, _ in exact_topk(q, self.vecs, self.ids, top_k=k)}
            recalls.append(len(ann & exact) / k)
        mean_recall = float(np.mean(recalls))
        self.assertGreaterEqual(mean_recall, 0.995, f"recall={mean_recall:.4f}")

    def test_dense_semantic_query(self):
        qv = self.emb.embed(["DNA'nın yapısı ve nükleotidler"])[0]
        hits = self.dense.search(qv, top_k=5)
        self.assertEqual(len(hits), 5)
        joined = " ".join(
            self.children[self.ids.index(cid)].text.lower() for cid, _ in hits
        )
        self.assertTrue(any(w in joined for w in ("dna", "nükleot", "baz")))

    def test_bm25_keyword_query(self):
        hits = self.bm25.search("fotosentez kloroplast", top_k=5)
        self.assertEqual(len(hits), 5)
        self.assertGreater(hits[0][1], 0.0)
        top_txt = self.children[self.ids.index(hits[0][0])].text.lower()
        self.assertTrue("fotosentez" in top_txt or "kloroplast" in top_txt)


if __name__ == "__main__":
    unittest.main()
