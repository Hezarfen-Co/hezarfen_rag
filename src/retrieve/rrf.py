"""Faz 1.4 — Reciprocal Rank Fusion (RRF).

Skor-ölçekleri kıyaslanamayan (dense cosine, BM25, sparse dot) sıralamaları
yalnız SIRA üzerinden birleştirir: rrf(d) = Σ_i 1/(k + rank_i(d)). k=60 (standart,
Cormack 2009). Kalibrasyon/ağırlık gerektirmez → sağlam varsayılan hibrit füzyon.
"""
from __future__ import annotations

from collections import defaultdict


def rrf_fuse(rankings, k: int = 60, top_k: int = 20):
    """rankings: her biri best-first (id, skor) listesi (skor yok sayılır, sıra kullanılır).
    Dönüş: (id, rrf_skoru) top_k, azalan."""
    fused: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, (cid, _score) in enumerate(ranking):
            fused[cid] += 1.0 / (k + rank + 1)          # rank 0-tabanlı → +1
    return sorted(fused.items(), key=lambda x: -x[1])[:top_k]
