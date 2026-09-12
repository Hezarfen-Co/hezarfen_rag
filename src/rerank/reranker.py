"""Faz 1.5 — BGE-reranker-v2-m3 cross-encoder yeniden sıralayıcı.

Cross-encoder (query,passage) çiftini birlikte kodlar → dense/BM25/sparse'tan daha
keskin relevance. Aday havuzunu (RRF top-N) alıp ilk 8-12'ye daraltır. Model **lazy**
yüklenir; GPU'da fp16. Sağlayıcı-değiştirilebilir: `rerank(query, items)` arayüzü.
"""
from __future__ import annotations

import os
import threading

# FlagReranker de tüm repoyu ister; yalnız gerekli dosyaları çözeriz (embedder ile aynı desen).
_NEEDED_PATTERNS = ["*.json", "*.model", "model.safetensors", "pytorch_model.bin",
                    "sentencepiece*", "tokenizer*", "config*"]


# #80: model surumu PINLENEBILIR olmali. `snapshot_download`'a `revision`
# verilmediginde her indirme depo HEAD'ini alir; yayinci agirligi guncellerse
# UYGULAMA SESSIZCE BASKA BIR MODELE GECER ve olculmus butun sayilar (kapi
# degerleri dahil) o modele ait OLMAKTAN CIKAR. Bos birakmak eski davranistir;
# uretimde bir commit sha'si verilmelidir.
MODEL_REVISION = os.environ.get("HEZARFEN_RERANK_REVISION") or None


class BGEReranker:
    """BAAI/bge-reranker-v2-m3. rerank(query, [(id,text)]) → [(id,skor)] azalan."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3",
                 use_fp16: bool | None = None, max_length: int = 512):
        self.model_name = model_name
        self.max_length = max_length
        self._use_fp16 = use_fp16
        self._model = None
        # #80: cift-kontrollu kilit (bkz. `_load`)
        self._load_lock = threading.Lock()

    def _resolve_model_path(self) -> str:
        import os
        if os.path.isdir(self.model_name):
            return self.model_name
        from huggingface_hub import snapshot_download
        try:
            return snapshot_download(self.model_name, allow_patterns=_NEEDED_PATTERNS,
                                     revision=MODEL_REVISION, local_files_only=True)
        except Exception:
            return snapshot_download(self.model_name, allow_patterns=_NEEDED_PATTERNS,
                                     revision=MODEL_REVISION)


# M4-6 (#80, EXP-010/OPS-07) -- MODEL YASAM DONGUSU.
#
# KOSULARAK KANITLANDI: `_load` kontrol-sonra-ata (check-then-set) desenindeydi
# ve HIC KILIT YOKTU. FastAPI uc noktalari `def` (sync) oldugu icin Starlette
# bunlari anyio worker havuzunda (varsayilan 40) GERCEKTEN paralel kosturuyor.
# Gercek sinifla olculdu: 8 thread -> **8 model yuklemesi** (1 olmaliydi).
#
# Basarisizlik: soguk servise 8 ogrenci ayni anda sorarsa BGE-M3 (+reranker)
# 8 kez paralel yuklenir -> 8 paralel snapshot_download (~2,3 GB x 2 model)
# ve/veya 8 kopya agirlik RAM'de -> OOM-kill. Hayatta kalsa bile yalniz son
# atanan ornek kullanilir (digerleri bosa harcanmis is).
#
# CIFT KONTROLLU KILIT: hizli yol (model zaten yuklu) kilide HIC girmez;
# yalniz ilk yukleme serilesir.
    def _load(self):
        if self._model is not None:               # hızlı yol: kilide girme
            return self._model
        with self._load_lock:
            if self._model is None:               # ikinci kontrol (kilit altında)
                self._model = self._build_model()
        return self._model

    def _build_model(self):
        """Ağır yükleme — ayrı metot (bkz. `embedder._build_model` gerekçesi)."""
        import torch
        from FlagEmbedding import FlagReranker
        fp16 = self._use_fp16
        if fp16 is None:
            fp16 = torch.cuda.is_available()
        return FlagReranker(self._resolve_model_path(), use_fp16=fp16)

    def warmup(self):
        """Modeli AÇILIŞTA yükle — ilk isteği bekletmemek için."""
        self._load()
        return self

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
