"""Faz 1.5 — BGE-reranker-v2-m3 cross-encoder yeniden sıralayıcı.

Cross-encoder (query,passage) çiftini birlikte kodlar → dense/BM25/sparse'tan daha
keskin relevance. Aday havuzunu (RRF top-N) alıp ilk 8-12'ye daraltır. Model **lazy**
yüklenir; GPU'da fp16. Sağlayıcı-değiştirilebilir: `rerank(query, items)` arayüzü.
"""
from __future__ import annotations

# FlagReranker de tüm repoyu ister; yalnız gerekli dosyaları çözeriz (embedder ile aynı desen).
_NEEDED_PATTERNS = ["*.json", "*.model", "model.safetensors", "pytorch_model.bin",
                    "sentencepiece*", "tokenizer*", "config*"]


class BGEReranker:
    """BAAI/bge-reranker-v2-m3. rerank(query, [(id,text)]) → [(id,skor)] azalan."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3",
                 use_fp16: bool | None = None, max_length: int = 512):
        self.model_name = model_name
        self.max_length = max_length
        self._use_fp16 = use_fp16
        self._model = None

    def _resolve_model_path(self) -> str:
        import os
        if os.path.isdir(self.model_name):
            return self.model_name
        from huggingface_hub import snapshot_download
        try:
            return snapshot_download(self.model_name, allow_patterns=_NEEDED_PATTERNS,
                                     local_files_only=True)
        except Exception:
            return snapshot_download(self.model_name, allow_patterns=_NEEDED_PATTERNS)

    def _load(self):
        if self._model is None:
            import torch
            from FlagEmbedding import FlagReranker
            fp16 = self._use_fp16
            if fp16 is None:
                fp16 = torch.cuda.is_available()
            self._model = FlagReranker(self._resolve_model_path(), use_fp16=fp16)
        return self._model

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def rerank(self, query: str, items, top_k: int | None = None,
               normalize: bool = True):
        """items: [(id, text)] → [(id, skor)] azalan. normalize=True → sigmoid (0-1)."""
        items = list(items)
        if not items:
            return []
        pairs = [[query, text] for _, text in items]
        scores = self._load().compute_score(pairs, max_length=self.max_length,
                                             normalize=normalize)
        if not isinstance(scores, list):
            scores = [scores]
        ranked = sorted(zip((i for i, _ in items), (float(s) for s in scores)),
                        key=lambda x: -x[1])
        return ranked[:top_k] if top_k else ranked
