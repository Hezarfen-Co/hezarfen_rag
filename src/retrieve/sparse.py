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
        self._doc_ids: list[str] = []          # her chunk'ın KAYNAĞI (#76)

    def build(self, ids, sparse_dicts, *, doc_id: str = ""):
        self._ids = list(ids)
        self._docs = [_norm_weights(d) for d in sparse_dicts]
        self._doc_ids = [doc_id] * len(self._ids)
        return self

    # M4-2 (#76): kaynak bazlı silme/ekleme. Sparse indeks saf Python listesi
    # olduğu için artımlı çalışır (BM25'ten farklı olarak yeniden kurma yok).
    def add(self, ids, sparse_dicts, *, doc_id: str = ""):
        yeni = list(ids)
        self._ids.extend(yeni)
        self._docs.extend(_norm_weights(d) for d in sparse_dicts)
        self._doc_ids.extend([doc_id] * len(yeni))
        return self

    def delete(self, doc_id: str) -> int:
        tut = [i for i, d in enumerate(self._doc_ids) if d != doc_id]
        silinen = len(self._ids) - len(tut)
        if not silinen:
            return 0
        self._ids = [self._ids[i] for i in tut]
        self._docs = [self._docs[i] for i in tut]
        self._doc_ids = [self._doc_ids[i] for i in tut]
        return silinen

    def doc_ids(self) -> set:
        return {d for d in self._doc_ids if d}

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
