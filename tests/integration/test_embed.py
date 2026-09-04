"""Faz 1.2 integration testi — BGE-M3 gerçek embedding (model indirir/yükler).
Model yüklenemezse (net/indirme yok) test ATLANIR."""
import unittest

import numpy as np

from src.embed import BGEM3Embedder, cosine_sim


def _model_ready():
    try:
        e = BGEM3Embedder()
        e.embed(["deneme"])          # ilk çağrı modeli indirir/yükler
        return e
    except Exception:
        return None


_E = _model_ready()


@unittest.skipUnless(_E is not None, "BGE-M3 modeli yüklenemedi (indirme/net yok)")
class BGEM3EmbedTests(unittest.TestCase):
    def test_dense_shape_and_norm(self):
        v = _E.embed(["DNA kalıtsal bilgiyi taşır.", "Fotosentez kloroplastta olur."])
        self.assertEqual(v.shape, (2, 1024))
        # BGE-M3 dense vektörleri L2-normalize (~1.0)
        norms = np.linalg.norm(v, axis=1)
        self.assertTrue(np.allclose(norms, 1.0, atol=0.05))

    def test_semantic_ordering_turkish(self):
        q = _E.embed(["DNA kalıtsal bilgiyi taşıyan moleküldür."])[0]
        yakin = _E.embed(["DNA genetik bilgiyi saklar ve aktarır."])[0]
        uzak = _E.embed(["Fotosentez bitkilerde kloroplastta gerçekleşir."])[0]
        self.assertGreater(cosine_sim(q, yakin), cosine_sim(q, uzak))

    def test_sparse_available(self):
        sp = _E.embed_sparse(["DNA çift sarmaldır"])
        self.assertEqual(len(sp), 1)
        self.assertTrue(len(sp[0]) > 0)                      # bazı token ağırlıkları


if __name__ == "__main__":
    unittest.main()
