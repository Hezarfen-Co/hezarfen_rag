"""Faz 1.3 birim testleri — Dense ANN↔exact recall (sentetik) + BM25 TR (model gerekmez)."""
import unittest

import numpy as np

from src.index import DenseIndex, exact_topk, BM25Index, tokenize


def _unit_vectors(n, d, seed=0):
    rng = np.random.default_rng(seed)
    v = rng.standard_normal((n, d)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v


class DenseRecallTests(unittest.TestCase):
    def test_ann_recall_vs_exact(self):
        d, n, k = 1024, 500, 20
        vecs = _unit_vectors(n, d, seed=1)
        ids = [f"c{i}" for i in range(n)]
        idx = DenseIndex(dim=d).build(ids, vecs)

        recalls = []
        for qi in range(0, n, 15):                      # ~34 sorgu
            q = vecs[qi]
            ann = {cid for cid, _ in idx.search(q, top_k=k)}
            exact = {cid for cid, _ in exact_topk(q, vecs, ids, top_k=k)}
            recalls.append(len(ann & exact) / k)
        mean_recall = float(np.mean(recalls))
        self.assertGreaterEqual(mean_recall, 0.995, f"recall={mean_recall:.4f}")

    def test_self_query_is_top1(self):
        d, n = 1024, 50
        vecs = _unit_vectors(n, d, seed=2)
        ids = [f"c{i}" for i in range(n)]
        idx = DenseIndex(dim=d).build(ids, vecs)
        top = idx.search(vecs[7], top_k=1)
        self.assertEqual(top[0][0], "c7")
        self.assertAlmostEqual(top[0][1], 1.0, places=3)

    def test_dim_mismatch_raises(self):
        idx = DenseIndex(dim=1024)
        with self.assertRaises(ValueError):
            idx.build(["a"], np.zeros((1, 8), dtype=np.float32))


class BM25TurkishTests(unittest.TestCase):
    def test_tokenize_tr_casefold(self):
        toks = tokenize("DNA'nın Yapısı İĞNE ışık")     # İ→i, I→ı korunur
        self.assertIn("dna", toks)
        self.assertIn("yapısı", toks)
        self.assertIn("iğne", toks)                      # İĞNE → iğne
        self.assertIn("ışık", toks)

    def test_search_finds_keyword_doc(self):
        ids = ["a", "b", "c"]
        texts = [
            "Fotosentez kloroplastta gerçekleşir.",
            "DNA nükleotidlerden oluşan çift sarmaldır.",
            "Mitoz hücre bölünmesi evreleri.",
        ]
        idx = BM25Index().build(ids, texts)
        top = idx.search("nükleotid DNA sarmal", top_k=3)
        self.assertEqual(top[0][0], "b")                 # en ilgili belge
        self.assertGreater(top[0][1], 0.0)

    def test_empty_doc_no_crash(self):
        # boş belge build/search'i bozmamalı; "metin" içeren belge üste gelmeli
        # (küçük korpusta IDF≈0 olmasın diye birkaç ilgisiz belge ekli)
        ids = ["x", "y", "d1", "d2", "d3"]
        texts = ["", "geçerli metin burada", "fotosentez", "mitoz", "dna sarmal"]
        idx = BM25Index().build(ids, texts)
        top = idx.search("metin", top_k=5)
        self.assertEqual(top[0][0], "y")


if __name__ == "__main__":
    unittest.main()
