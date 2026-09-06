"""Faz 1.3 — BM25 lexical indeks (rank_bm25), TR-normalize, köksüz.

Tek alan (chunk metni). TR-güvenli katlama (`fold_for_match`: İ/ı doğru,
görünmezler temiz) + Unicode kelime tokenizasyonu. **Köksüz**: stemming/kök
bulma yok — dense ile tamamlayıcı lexical sinyal (hibrit RRF, Faz 1.4). Terim
eşleşmesi (özel ad, kod, sayı) dense'in kaçırdığını yakalar.
"""
from __future__ import annotations

import re

import numpy as np

from src.text.tr_normalize import fold_for_match

_WORD = re.compile(r"\w+", re.UNICODE)          # Türkçe harfler dahil (folded)
_EMPTY = "∅"                                # boş belge placeholder (∅)


def tokenize(text: str) -> list[str]:
    """TR-katlanmış metni token listesine ayır (köksüz)."""
    return _WORD.findall(fold_for_match(text))


class BM25Index:
    """BM25Okapi sarmalayıcı. build(ids, texts) → search(query, k)."""

    def __init__(self):
        self._bm25 = None
        self._ids: list[str] = []
        self._built = False

    def build(self, ids, texts):
        from rank_bm25 import BM25Okapi
        self._ids = list(ids)
        self._built = True
        if not texts:                          # boş korpus → BM25Okapi([]) ZeroDivision (avgdl)
            self._bm25 = None
            return self
        corpus = [tokenize(t) or [_EMPTY] for t in texts]   # boş → placeholder
        self._bm25 = BM25Okapi(corpus)
        return self

    def search(self, query, top_k: int = 20):
        """(chunk_id, bm25_skoru) listesi, skor azalan. Boş indeks/sorgu → []."""
        if not self._built:
            raise RuntimeError("önce build() çağır")
        if self._bm25 is None:                 # boş korpus build edildi → sonuç yok
            return []
        toks = tokenize(query)
        if not toks:                           # boş/whitespace/simgesiz sorgu → çöp sonuç verme
            return []
        scores = self._bm25.get_scores(toks)
        order = np.argsort(-scores)[:top_k]
        return [(self._ids[i], float(scores[i])) for i in order]

    def __len__(self):
        return len(self._ids)
