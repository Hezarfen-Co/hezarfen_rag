"""Faz 1.4 — BGE-M3 sparse (lexical_weights) indeksi + nokta-çarpım araması.

BGE-M3 sparse çıktısı: {token_id(str) -> ağırlık(float)}. Sparse benzerlik =
ortak token'lar üzerinde ağırlık çarpımlarının toplamı (sparse dot). Küçük korpusta
doğrudan hesaplanır; ölçekte Qdrant sparse-vector arka ucuna taşınır (aynı arayüz).
"""
from __future__ import annotations

import numpy as np


def _norm_weights(d) -> dict[str, float]:
    return {str(k): float(v) for k, v in d.items()}


class SparseIndex:
    """build(ids, sparse_dicts) → search(query_sparse, k). Lexical tamamlayıcı sinyal."""

    def __init__(self):
        self._ids: list[str] = []
        self._docs: list[dict[str, float]] = []

    def build(self, ids, sparse_dicts):
        self._ids = list(ids)
        self._docs = [_norm_weights(d) for d in sparse_dicts]
        return self

    def search(self, query_sparse, top_k: int = 30):
        q = _norm_weights(query_sparse)
        scores = np.zeros(len(self._docs), dtype=np.float32)
        for i, d in enumerate(self._docs):
            small, big = (q, d) if len(q) <= len(d) else (d, q)   # az anahtar üzerinde dön
            scores[i] = sum(w * big.get(t, 0.0) for t, w in small.items())
        order = np.argsort(-scores)[:top_k]
        return [(self._ids[i], float(scores[i])) for i in order]

    def __len__(self):
        return len(self._ids)
