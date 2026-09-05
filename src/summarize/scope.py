"""Özet çıkarma — KAPSAM çözümü (soru-cevaptan FARKI: retrieval/embed KULLANMAZ).

`resolve_scope`, verilen sayfa aralığı VE/VEYA span_id listesine göre kapsamdaki
RETRIEVABLE (bkz. `CanonicalUnit.retrievable` — is_body zaten `units_from_parsed`
aşamasında filtrelendi, burada yalnız `retrieval_disi` olmayanlar kalır) birimleri
DETERMİNİSTİK biçimde, `doc.units` okuma sırası KORUNARAK döndürür.

Soru-cevaptan (src/generate/Generator) mimari FARKI budur: kaynak seçimi bir
SORU'ya göre hibrit retrieval + rerank ile DEĞİL, önceden belirlenmiş bir
KAPSAMLA (sayfa aralığı/span_id listesi) yapılır — aynı girdi HER ZAMAN aynı
kapsamı üretir (embed/indeks/skor değişse bile kapsam DEĞİŞMEZ).
"""
from __future__ import annotations

from typing import Iterable

from ..ingest.canonical import CanonicalDoc, CanonicalUnit


def resolve_scope(doc: CanonicalDoc, *, pages: Iterable[int] | None = None,
                  span_ids: Iterable[str] | None = None) -> list[CanonicalUnit]:
    """`doc.units`'tan kapsamdaki RETRIEVABLE birimleri okuma sırasıyla döndürür.

    - `pages`: kapsamdaki sayfa numaraları (liste/`range`/küme — herhangi bir
      `int` iterable'ı kabul edilir).
    - `span_ids`: kapsamdaki span_id'ler (birime tekil eşleşir).
    - Bir birim SAYFA kapsamında VEYA span_id kapsamında ise dahil edilir (VEYA
      mantığı — ikisi birden verilirse birleşimleri alınır).
    - `pages` VE `span_ids` ikisi de boş/None ise -> BOŞ KAPSAM -> `[]` (retrieval
      YOK, varsayılan olarak "her şeyi özetle" YAPILMAZ — çağıran taraf kapsamı
      AÇIKÇA belirtmek zorunda; bu da `Summarizer.summarize()`'ın FAIL-CLOSED
      "empty_scope" davranışının ön-koşuludur).
    """
    page_set = set(pages) if pages else None
    span_set = set(span_ids) if span_ids else None
    if page_set is None and span_set is None:
        return []

    out: list[CanonicalUnit] = []
    for u in doc.units:
        if not u.retrievable:
            continue
        in_scope = (page_set is not None and u.page in page_set) or \
                  (span_set is not None and u.span_id in span_set)
        if in_scope:
            out.append(u)
    return out
