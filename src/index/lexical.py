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
        self._texts: list[str] = []
        self._docs: list[str] = []             # her chunk'ın KAYNAĞI (#76)
        self._built = False

    def build(self, ids, texts, *, doc_id: str = ""):
        self._ids = list(ids)
        self._texts = list(texts)
        self._docs = [doc_id] * len(self._ids)
        self._built = True
        return self._rebuild()

    def _rebuild(self):
        from rank_bm25 import BM25Okapi
        if not self._texts:                    # boş korpus → BM25Okapi([]) ZeroDivision (avgdl)
            self._bm25 = None
            return self
        corpus = [tokenize(t) or [_EMPTY] for t in self._texts]   # boş → placeholder
        self._bm25 = BM25Okapi(corpus)
        return self

    # M4-2 (#76): silme/ekleme. `rank_bm25` ARTIMLI DEGILDIR (IDF tum korpusa
    # bagli), bu yuzden her degisiklikte indeks yeniden kurulur. Bu bilincli:
    # dogru sonuc yavas olmaktan iyidir ve BM25 kurulumu (saniyenin altinda)
    # embed'in yaninda ihmal edilebilir.
    def add(self, ids, texts, *, doc_id: str = ""):
        self._ids.extend(ids)
        self._texts.extend(texts)
        self._docs.extend([doc_id] * len(list(ids)))
        self._built = True
        return self._rebuild()

    def delete(self, doc_id: str) -> int:
        """Bir kaynağın tüm chunk'larını siler. Döner: silinen sayısı."""
        tut = [i for i, d in enumerate(self._docs) if d != doc_id]
        silinen = len(self._ids) - len(tut)
        if not silinen:
            return 0
        self._ids = [self._ids[i] for i in tut]
        self._texts = [self._texts[i] for i in tut]
        self._docs = [self._docs[i] for i in tut]
        self._rebuild()
        return silinen

    def doc_ids(self) -> set:
        return {d for d in self._docs if d}

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
