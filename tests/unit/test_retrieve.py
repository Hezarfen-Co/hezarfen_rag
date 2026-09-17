"""Faz 1.4 birim testleri — RRF füzyon matematiği + SparseIndex (model gerekmez)."""
import unittest

from src.retrieve import rrf_fuse, SparseIndex


class RRFTests(unittest.TestCase):
    def test_fusion_order_and_dedup(self):
        r1 = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
        r2 = [("b", 5.0), ("d", 4.0), ("a", 3.0)]
        fused = rrf_fuse([r1, r2], k=60, top_k=10)
        order = [cid for cid, _ in fused]
        self.assertEqual(order, ["b", "a", "d", "c"])       # b>a>d>c (elde hesap)
        # b: 1/62 + 1/61 ; a: 1/61 + 1/63
        b = 1 / 62 + 1 / 61
        self.assertAlmostEqual(dict(fused)["b"], b, places=9)
        self.assertEqual(len(fused), 4)                     # dedup: 4 benzersiz id

    def test_score_ignored_only_rank_matters(self):
        # skor büyüklüğü değil SIRA önemli: iki listede de ilk olan kazanır
        r1 = [("x", 0.001), ("y", 999.0)]
        r2 = [("x", 0.002), ("y", 999.0)]
        fused = dict(rrf_fuse([r1, r2], k=60))
        self.assertGreater(fused["x"], fused["y"])

    def test_top_k_truncation(self):
        r = [[(f"c{i}", 1.0) for i in range(50)]]
        self.assertEqual(len(rrf_fuse(r, top_k=20)), 20)


class SparseIndexTests(unittest.TestCase):
    def test_dot_product_ranking(self):
        ids = ["a", "b", "c"]
        docs = [{"1": 0.5, "2": 0.3}, {"2": 0.9, "3": 0.1}, {"4": 1.0}]
        idx = SparseIndex().build(ids, docs, school="okul-a")
        top = idx.search({"2": 1.0, "3": 0.5}, top_k=3, school="okul-a")
        self.assertEqual(top[0][0], "b")                    # 0.9+0.05=0.95
        self.assertAlmostEqual(top[0][1], 0.95, places=5)
        self.assertEqual(top[-1][0], "c")                   # ortak yok → 0

    def test_str_int_keys_normalized(self):
        idx = SparseIndex().build(["a"], [{1: 0.5, 2: 0.5}], school="okul-a")   # int anahtar
        top = idx.search({"1": 1.0}, top_k=1, school="okul-a")                  # str anahtar sorgu
        self.assertAlmostEqual(top[0][1], 0.5, places=5)


class QueryEmbeddingIntentTests(unittest.TestCase):
    """Sorgu, sağlayıcının SORGU niyetiyle gömülmeli.

    `HybridRetriever.retrieve` sorguyu `embed()` (pasaj niyeti) ile gömüyordu:
    uzak sağlayıcılarda bu, istediğimiz sorgu/pasaj ayrımını SESSİZCE kaldırır
    (Voyage'a `document`, Cohere'e `search_document`). Yerel BGE-M3'te ayrım
    yoktur → tek kod yolu, sağlayıcının sunduğu kadar ayrım."""

    class _Emb:
        """Yerel yol benzeri: `embed_query` YOK (BGE-M3'te ayrım yok)."""
        sparse_supported = False

        def __init__(self):
            self.cagrilar = []

        def embed(self, texts, batch_size=12):
            import numpy as np
            self.cagrilar.append(("passage", list(texts)))
            return np.ones((len(texts), 2), dtype="float32")

        def embed_sparse(self, texts, batch_size=12):
            return [{} for _ in texts]

    class _SplitEmb(_Emb):
        """Uzak sağlayıcı benzeri: sorgu/pasaj ayrımı SUNUYOR."""

        def embed_query(self, text):
            import numpy as np
            self.cagrilar.append(("query", [text]))
            return np.ones((1, 2), dtype="float32")

    class _Index:
        def search(self, q, k, school=None):
            return []

    def _retr(self, ayrim: bool):
        from src.retrieve import HybridRetriever
        emb = self._SplitEmb() if ayrim else self._Emb()
        return HybridRetriever(emb, self._Index(), self._Index()), emb

    def test_query_intent_is_used_when_the_provider_supports_it(self):
        rr, emb = self._retr(True)
        rr.retrieve("fotosentez nedir", top_k=3, school="okul-a")
        self.assertEqual(emb.cagrilar[0][0], "query", "sorgu 'query' niyetiyle gömülmeli")

    def test_local_provider_without_the_split_still_uses_embed(self):
        """BGE-M3'te `embed_query` YOK: davranış eskisi gibi `embed()` kalmalı."""
        rr, emb = self._retr(False)
        rr.retrieve("fotosentez nedir", top_k=3, school="okul-a")
        self.assertEqual(emb.cagrilar[0][0], "passage")


if __name__ == "__main__":
    unittest.main()
