"""Faz 1.2 birim testleri — cosine yardımcıları + embedder lazy-load (model gerekmez)."""
import unittest

import numpy as np

from src.embed import cosine_sim, cosine_matrix, BGEM3Embedder


class CosineTests(unittest.TestCase):
    def test_identical(self):
        self.assertAlmostEqual(cosine_sim([1, 2, 3], [1, 2, 3]), 1.0, places=6)

    def test_orthogonal(self):
        self.assertAlmostEqual(cosine_sim([1, 0], [0, 1]), 0.0, places=6)

    def test_zero_vector(self):
        self.assertEqual(cosine_sim([0, 0], [1, 1]), 0.0)

    def test_matrix_shape_and_order(self):
        q = [1.0, 0.0]
        m = np.array([[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]])
        scores = cosine_matrix(q, m)
        self.assertEqual(scores.shape, (3,))
        self.assertEqual(int(np.argmax(scores)), 0)          # en benzer satır 0
        self.assertGreater(scores[2], scores[1])             # [0.9,0.1] > [0,1]


class BGEM3LazyTests(unittest.TestCase):
    def test_lazy_no_load_on_construct(self):
        e = BGEM3Embedder()
        self.assertFalse(e.loaded)                            # model import/indirme yok
        self.assertEqual(e.dim, 1024)

    def test_empty_embed_no_model(self):
        e = BGEM3Embedder()
        v = e.embed([])                                       # boş → model yüklenmez
        self.assertEqual(v.shape, (0, 1024))
        self.assertFalse(e.loaded)


if __name__ == "__main__":
    unittest.main()
