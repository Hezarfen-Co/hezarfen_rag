"""Faz 1.2 — BGE-M3 embedder (dense + sparse).

Sağlayıcı-değiştirilebilir arayüz (`Embedder`): ileride e5-large/TurkEmbed baseline
aynı arayüzle eklenir (mimari §0.1: model = aday, benchmark'ta yarışır).
Model **lazy** yüklenir → import ucuz, testte model olmadan da kurulabilir.
GPU varsa otomatik kullanılır (fp16). Dense vektörler L2-normalize (cosine = dot).
"""
from __future__ import annotations
from typing import Protocol

import numpy as np


def cosine_sim(a, b) -> float:
    a = np.asarray(a, dtype=np.float32); b = np.asarray(b, dtype=np.float32)
    na = np.linalg.norm(a); nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def cosine_matrix(query, matrix) -> np.ndarray:
    """query (d,) ile matrix (n,d) arasında cosine skorları (n,). Satırlar normalize varsayılmaz."""
    q = np.asarray(query, dtype=np.float32)
    m = np.asarray(matrix, dtype=np.float32)
    qn = q / (np.linalg.norm(q) + 1e-12)
    mn = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-12)
    return mn @ qn


class Embedder(Protocol):
    dim: int
    def embed(self, texts: list[str], batch_size: int = 12) -> np.ndarray: ...


# FlagEmbedding, repo'nun TAMAMINI (onnx/model.onnx_data ~2GB dahil) snapshot_download
# ile ister; biz yalnız PyTorch modelini kullandığımız için sadece gerekli dosyaları
# çekeriz. Böylece 2GB onnx inmez ve cache tam sayılmadığı için üretilen
# IncompleteSnapshotError'dan kaçınılır.
_NEEDED_PATTERNS = ["*.json", "*.model", "pytorch_model.bin", "model.safetensors",
                    "sentencepiece*", "tokenizer*", "config*",
                    "colbert_linear.pt", "sparse_linear.pt"]


class BGEM3Embedder:
    """BGE-M3 (BAAI/bge-m3). Dense 1024-dim + opsiyonel sparse."""
    dim = 1024

    def __init__(self, model_name: str = "BAAI/bge-m3", use_fp16: bool | None = None,
                 max_length: int = 8192):
        self.model_name = model_name
        self.max_length = max_length
        self._use_fp16 = use_fp16
        self._model = None

    def _resolve_model_path(self) -> str:
        """Model dizinini çöz: yerel dizinse doğrudan; değilse yalnız gerekli
        dosyaları (onnx hariç) cache'ten ver, yoksa indir. FlagEmbedding yerel
        dizin görünce snapshot_download'ı atlar (2GB onnx istemez)."""
        import os
        if os.path.isdir(self.model_name):
            return self.model_name
        from huggingface_hub import snapshot_download
        try:                                          # önce cache (ağsız)
            return snapshot_download(self.model_name, allow_patterns=_NEEDED_PATTERNS,
                                     local_files_only=True)
        except Exception:                             # cache yok → gerekli dosyaları indir
            return snapshot_download(self.model_name, allow_patterns=_NEEDED_PATTERNS)

    def _load(self):
        if self._model is None:
            import torch
            from FlagEmbedding import BGEM3FlagModel
            fp16 = self._use_fp16
            if fp16 is None:
                fp16 = torch.cuda.is_available()      # fp16 yalnız GPU'da
            self._model = BGEM3FlagModel(self._resolve_model_path(), use_fp16=fp16)
        return self._model

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def embed(self, texts: list[str], batch_size: int = 12) -> np.ndarray:
        """Dense embedding matrisi (n, 1024), L2-normalize."""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out = self._load().encode(texts, batch_size=batch_size,
                                  max_length=self.max_length,
                                  return_dense=True, return_sparse=False)
        return np.asarray(out["dense_vecs"], dtype=np.float32)

    def embed_sparse(self, texts: list[str], batch_size: int = 12) -> list[dict]:
        """Sparse (lexical) ağırlıklar — hibrit retrieval için (token-id -> ağırlık)."""
        if not texts:
            return []
        out = self._load().encode(texts, batch_size=batch_size,
                                  max_length=self.max_length,
                                  return_dense=False, return_sparse=True)
        return list(out["lexical_weights"])

    def embed_chunks(self, chunks, batch_size: int = 12):
        """Chunk listesi → (chunk_id listesi, dense matris). chunk.text embed edilir."""
        ids = [c.chunk_id for c in chunks]
        vecs = self.embed([c.text for c in chunks], batch_size=batch_size)
        return ids, vecs
