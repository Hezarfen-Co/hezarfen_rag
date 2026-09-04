"""Faz 1.3 — Qdrant yerel (gömülü) dense vektör indeksi + exact referans.

BGE-M3 dense (1024-dim, L2-normalize) → cosine mesafe. Gömülü mod (sunucu yok):
`path=None` → in-memory (test); `path=...` → kalıcı yerel depo. Üretimde Qdrant
sunucu konteyneri aynı arayüzle takılır.

Kabul (plan 1.3): ANN recall ≥ 0.995 (exact brute-force'a karşı). NOT: Qdrant'ın
gömülü yerel modu küçük koleksiyonda exact hesaplar (recall=1.0); gerçek HNSW/ANN
kaybı ölçekte (sunucu) yeniden ölçülecek. `exact_topk` referans olarak burada.
"""
from __future__ import annotations

import numpy as np

_COLLECTION = "chunks"


def exact_topk(query_vec, matrix, ids, top_k: int = 20):
    """Brute-force cosine (referans doğruluk). matrix satırları normalize varsayılmaz."""
    from src.embed import cosine_matrix
    scores = cosine_matrix(query_vec, matrix)
    order = np.argsort(-scores)[:top_k]
    return [(ids[i], float(scores[i])) for i in order]


class DenseIndex:
    """Qdrant gömülü dense indeks. build(ids, vectors) → search(query_vec, k)."""

    def __init__(self, dim: int = 1024, path: str | None = None,
                 collection: str = _COLLECTION):
        self.dim = dim
        self.collection = collection
        self._path = path
        self._client = None
        self._ids: list[str] = []

    def _c(self):
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = (QdrantClient(path=self._path) if self._path
                            else QdrantClient(":memory:"))
        return self._client

    def build(self, ids, vectors, payloads=None):
        from qdrant_client.models import Distance, VectorParams, PointStruct
        c = self._c()
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[1] != self.dim:
            raise ValueError(f"vectors (n,{self.dim}) olmalı, geldi {vectors.shape}")
        if c.collection_exists(self.collection):
            c.delete_collection(self.collection)
        c.create_collection(
            self.collection,
            vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
        )
        pts = []
        for i, (cid, v) in enumerate(zip(ids, vectors)):
            pl = {"chunk_id": cid}
            if payloads:
                pl.update(payloads[i])
            pts.append(PointStruct(id=i, vector=v.tolist(), payload=pl))
        c.upsert(self.collection, points=pts)
        self._ids = list(ids)
        return self

    def search(self, query_vec, top_k: int = 20):
        """(chunk_id, skor) listesi, skor azalan. Skor = cosine (dense normalize)."""
        c = self._c()
        q = np.asarray(query_vec, dtype=np.float32).tolist()
        res = c.query_points(self.collection, query=q, limit=top_k).points
        return [(p.payload["chunk_id"], float(p.score)) for p in res]

    def __len__(self):
        return len(self._ids)
