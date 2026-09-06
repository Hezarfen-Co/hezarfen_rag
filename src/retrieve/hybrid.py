"""Faz 1.4 — Hibrit retrieval: dense (top40) + BM25 (top40) + sparse (top30) → RRF.
Faz 1.6 — KASA İZOLASYONU: opsiyonel `meta` (chunk_id→{sinif,ders}) + `role_ctx`
ile RRF sonrası, trim ÖNCESİ yetki filtresi (guard.can_access). Rolün göremeyeceği
sınıf/ders chunk'ları ELENİR (0 yetkisiz sızıntı). Sunucu-tarafı rol (bkz. src/guard/
roles.py); istemci-header'a güvenilmez.

Üç tamamlayıcı sinyal: dense (anlam), BM25 (köksüz lexical), sparse (öğrenilmiş lexical).
"""
from __future__ import annotations

from src.retrieve.rrf import rrf_fuse


class HybridRetriever:
    def __init__(self, embedder, dense, bm25, sparse=None, rrf_k: int = 60, meta=None):
        self.embedder = embedder
        self.dense = dense
        self.bm25 = bm25
        self.sparse = sparse
        self.rrf_k = rrf_k
        # Opsiyonel {chunk_id: {"sinif":..., "ders":...}} — kasa izolasyonu için.
        # None ise filtre uygulanmaz (tek-kasa/backward-compat).
        self.meta = meta

    def _allowed(self, cid, role_ctx) -> bool:
        """Kasa izolasyonu: chunk'ın sinif/ders'i role_ctx'in erişebileceği kapsamda mı.
        meta'da olmayan chunk -> no-leak DENY (bilinmeyen kaynak erişilemez)."""
        from src.guard import can_access
        m = self.meta.get(cid) if self.meta else None
        if m is None:
            return False
        return can_access(role_ctx, sinif=m.get("sinif"), ders=m.get("ders"))

    def retrieve(self, query: str, top_k: int = 20,
                 dense_k: int = 40, bm25_k: int = 40, sparse_k: int = 30,
                 role_ctx=None):
        """Sorgu → RRF-birleştirilmiş (chunk_id, rrf_skoru) top_k. `role_ctx` verilirse
        KASA İZOLASYONU: yetkisiz sınıf/ders chunk'ları elenir (trim'den ÖNCE).

        FAIL-CLOSED: `role_ctx` verildi AMA `meta` yoksa → boş liste döner (sızıntıdansa
        hiç sonuç vermek yeğ; rol-filtresi istendiği hâlde uygulanamıyorsa açık bırakma).
        Boş/whitespace sorgu → boş liste (indeksleri boşuna dövme, çöp sonuç üretme)."""
        if not query or not query.strip():
            return []
        if role_ctx is not None and self.meta is None:
            return []                                            # fail-closed (bkz. docstring)
        qv = self.embedder.embed([query])[0]
        rankings = [self.dense.search(qv, dense_k), self.bm25.search(query, bm25_k)]
        if self.sparse is not None:
            qs = self.embedder.embed_sparse([query])[0]
            rankings.append(self.sparse.search(qs, sparse_k))
        fused = rrf_fuse(rankings, k=self.rrf_k, top_k=None)     # tümü (trim sonra)
        if role_ctx is not None:                                 # meta burada garanti var
            fused = [(cid, s) for cid, s in fused if self._allowed(cid, role_ctx)]
        return fused[:top_k]
