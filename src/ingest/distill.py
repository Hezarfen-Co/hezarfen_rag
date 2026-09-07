"""Faz — Veri damıtma / distillation (#8): indeks öncesi TEKRAR ve NEAR-DUPLICATE
birimleri + boilerplate'i ayıklar. Amaç: retrieval gürültüsünü azalt (aynı içerik
top-k'yi doldurup çeşitliliği düşürmesin), gereksiz embedding/depolama maliyetini kes.

- EXACT-duplicate: normalize (TR-katlanmış) metni AYNI olan birimler → ilk kopya
  kalır, gerisi düşer (boilerplate/tekrar bunu da kapsar: çok tekrarlanan uyarı
  cümleleri tek kopyaya iner).
- NEAR-duplicate: imza (ilk+son birkaç sözcük) BUCKET'ında SequenceMatcher benzerliği
  eşik üstündeyse düşer — karşılaştırma yalnız aynı imzalı birkaç birime yapılır
  (O(n·küçük), tüm-çiftler O(n²) değil).

isolate.py (sızıntı) + tr_normalize (temizlik) ile TAMAMLAYICI: onlar yanlış-türü/
gürültü-karakteri, bu TEKRARI ayıklar. Güvenlik: yalnız DUPLICATE düşer; benzersiz
öğretici içerik ASLA düşmez (izolasyon-gevşetme değil, çeşitlilik-artırma).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from ..text.tr_normalize import fold_for_match


def _signature(folded: str) -> tuple:
    """Ucuz near-dup bucket imzası: ilk 8 sözcük (kısa metinde tümü). Yalnız
    KARŞILAŞTIRMAYI SINIRLAR (correctness ratio kontrolündedir) — boilerplate/tekrar
    genelde ortak önek taşıdığından ilk-N iyi bucket'lar; O(n²) karşılaştırmayı önler."""
    toks = folded.split()
    return tuple(toks[:8])


@dataclass
class DistillReport:
    total: int
    kept: int
    dropped_exact: int
    dropped_near: int

    def as_dict(self) -> dict:
        return {"total": self.total, "kept": self.kept,
                "dropped_exact": self.dropped_exact, "dropped_near": self.dropped_near}


def distill_units(units: list, *, near_threshold: float = 0.92):
    """(kept_units, DistillReport). Okuma sırasını KORUR; ilk-görülen kopya kalır.
    Boş/çok kısa metin (< 3 sözcük) dedup'a girmez (chunk aşaması ele alır)."""
    kept: list = []
    seen_exact: set[str] = set()
    by_sig: dict[tuple, list[str]] = defaultdict(list)   # imza -> tutulan folded metinler
    dropped_exact = dropped_near = 0

    for u in units:
        folded = fold_for_match(getattr(u, "text", "") or "")
        if len(folded.split()) < 3:                      # çok kısa → dedup dışı, aynen tut
            kept.append(u)
            continue
        if folded in seen_exact:                         # birebir tekrar / boilerplate
            dropped_exact += 1
            continue
        sig = _signature(folded)
        is_near = False
        for prev in by_sig.get(sig, ()):                 # yalnız aynı imzalı birkaç birim
            if SequenceMatcher(None, folded, prev).ratio() >= near_threshold:
                is_near = True
                break
        if is_near:
            dropped_near += 1
            continue
        seen_exact.add(folded)
        by_sig[sig].append(folded)
        kept.append(u)

    return kept, DistillReport(total=len(units), kept=len(kept),
                               dropped_exact=dropped_exact, dropped_near=dropped_near)
