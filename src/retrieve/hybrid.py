"""Faz 1.4 — Hibrit retrieval: dense (top40) + BM25 (top40) + sparse (top30) → RRF.

Üç tamamlayıcı sinyal: dense (anlam), BM25 (köksüz lexical), sparse (BGE-M3 öğrenilmiş
lexical). RRF ile sıra-tabanlı birleştirilir (kalibrasyonsuz). Reranker (Faz 1.5) bu
aday havuzunu daraltıp yeniden sıralar. Recall@20 ölçümü golden set (Faz 1.8) sonrası.
"""
from __future__ import annotations

from src.retrieve.rrf import rrf_fuse


class HybridRetriever:
    def __init__(self, embedder, dense, bm25, sparse=None, rrf_k: int = 60):
        self.embedder = embedder
        self.dense = dense
        self.bm25 = bm25
        self.sparse = sparse
        self.rrf_k = rrf_k

    def retrieve(self, query: str, top_k: int = 20,
                 dense_k: int = 40, bm25_k: int = 40, sparse_k: int = 30):
        """Sorgu → RRF-birleştirilmiş (chunk_id, rrf_skoru) top_k."""
        qv = self.embedder.embed([query])[0]
        rankings = [self.dense.search(qv, dense_k), self.bm25.search(query, bm25_k)]
        if self.sparse is not None:
            qs = self.embedder.embed_sparse([query])[0]
            rankings.append(self.sparse.search(qs, sparse_k))
        return rrf_fuse(rankings, k=self.rrf_k, top_k=top_k)
