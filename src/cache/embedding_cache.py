"""EmbeddingCache — `(model, text) -> vektör` (bkz. docs/OPTIMIZATION.md §C).

RagArt dersi: embedding hesaplaması pahalı ama METİN + MODEL sabitse sonuç
DAİMA aynıdır (deterministik) -> TTL sonsuz (`None`) güvenli varsayılan.
İndeksleme (aynı chunk yeniden embed edilirse) + sorgu embed'ini (aynı soru
tekrar sorulursa) amortize eder.

Anahtar `sha256(model + "::" + text)` — model DEĞİŞİRSE (ör. bge-m3 ->
e5-large) anahtar da değişir, farklı modellerin vektörleri asla karışmaz."""
from __future__ import annotations

import hashlib
from typing import Iterable, Mapping, Sequence

from .base import BaseCache, SQLiteCache


def embedding_key(model: str, text: str) -> str:
    h = hashlib.sha256()
    h.update((model or "").encode("utf-8"))
    h.update(b"::")
    h.update((text or "").encode("utf-8"))
    return h.hexdigest()


class EmbeddingCache:
    """key=sha256(model+"::"+text) -> vektör (list[float]). TTL varsayılan
    sonsuz (`ttl=None`) — RagArt dersi: embedding sonucu deterministik."""

    def __init__(self, backend: BaseCache | None = None, *, model: str = "",
                ttl: float | None = None):
        self.backend = backend if backend is not None else SQLiteCache()
        self.model = model
        self.ttl = ttl

    def _key(self, text: str, model: str | None = None) -> str:
        return embedding_key(model if model is not None else self.model, text)

    def get(self, text: str, *, model: str | None = None):
        return self.backend.get(self._key(text, model))

    def set(self, text: str, vector, *, model: str | None = None) -> None:
        # list[float]'a normalize et — numpy array/tensor cache'e SIZMASIN
        # (pickle her ikisini de kabul eder ama liste daha taşınabilir/ucuz).
        vec = [float(x) for x in vector]
        self.backend.set(self._key(text, model), vec, ttl=self.ttl)

    def get_many(self, texts: Sequence[str], *, model: str | None = None):
        """(hits: {text: vektör}, misses: [text, ...]) — `misses` giriş sırasını
        korur (embedder yalnız bu metinleri modele verecek)."""
        hits: dict[str, list] = {}
        misses: list[str] = []
        for t in texts:
            v = self.get(t, model=model)
            if v is None:
                misses.append(t)
            else:
                hits[t] = v
        return hits, misses

    def set_many(self, items: Mapping[str, object] | Iterable[tuple], *,
                model: str | None = None) -> None:
        """items: {text: vektör} ya da [(text, vektör), ...] (batch miss-merge
        sonrası embedder'ın hesapladığı yeni vektörleri toptan cache'e yazar)."""
        pairs = items.items() if hasattr(items, "items") else items
        for text, vector in pairs:
            self.set(text, vector, model=model)

    @property
    def stats(self):
        return self.backend.stats
