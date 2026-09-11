"""Faz 1.1 — Çok-temsilli chunking (çocuk + üst), başlık-sınırı farkında.

Kaynak: `CanonicalDoc` (retrievable birimler). Çıktı: child + parent chunk'lar;
her chunk kaynak birim **span_id**'lerini taşır → atıf korunur. Tokenizer henüz
yok; `approx_tokens` yaklaşık ölçüdür (embedding modeli gelince gerçek sayım, 1.2).
"""
from __future__ import annotations
import os
from collections import Counter
from dataclasses import dataclass, field, asdict

from ..ingest.canonical import CanonicalDoc, CanonicalUnit
from ..ingest.pdf_parse import HEADING

# Yaklaşık token: Türkçe eklemeli → kelime başına ~1.4 subword.
_TOK_PER_WORD = 1.4
CHILD_MIN = 150      # bir çocuk en az bu kadar (küçük bloklar birleşir)
CHILD_FLUSH = 250    # bu değere ulaşınca çocuğu kapat (150-300 bandının ortası)
PARENT_MIN = 700     # bir üst en az bu kadar
PARENT_FLUSH = 1000  # üst chunk flush eşiği (700-1500 bandı)

# M2-1 (#53, EXP-010/ACC-02 + EVAL-07) -- SAYFA HIZALI CHILD CHUNK.
#
# Atif chunk duzeyinde uretiliyor (`generator.py`: citations[i].pages =
# _pages_for_span_ids(ctx.span_ids)), yani atif chunk'in TUM span'larinin
# sayfalarini tasiyor. Child chunk'lar sayfa sinirini serbestce astigi icin
# her asan chunk atifa FAZLADAN sayfa ekliyor.
#
# GERCEK KITAPLA OLCULDU (10-biyoloji, 194 sayfa): child chunk'larin %63,4'u
# (147/232) sayfa sinirini asiyordu. 136 item'da dogru sayfa %100 bulunmus ama
# ortalama 0,94 FAZLA sayfa atiflanmisti (gold 1,24 <-> model 2,01 sayfa).
# `precision_page`'in teorik tavani min(1, gold/cited) ~= 0,712; olculen 0,645
# bu tavanin %91'i. Yani 0,99 kapisi eski chunk'lamayla MATEMATIKSEL OLARAK
# ulasilamazdi -- daha buyuk embedding modeli bunu duzeltmez.
#
# DURUST SINIR: bu degisiklik chunk SAYISINI artirir ve sayfa sonunda kalan
# kucuk parcalar CHILD_MIN'in altina duser; bu retrieval recall'unu bozabilir.
# Bu yuzden varsayilan env ile secilir ve karar ABLATION'a baglidir (#53 kabul
# kriteri: precision_page yukselmeli VE recall@5/@20 dusmemeli).
PAGE_ALIGNED_DEFAULT = os.environ.get("RAG_CHUNK_PAGE_ALIGNED", "1") not in (
    "0", "", "false", "False")


def approx_tokens(text: str) -> int:
    return round(len(text.split()) * _TOK_PER_WORD)


@dataclass
class Chunk:
    chunk_id: str
    level: str                                 # "child" | "parent"
    text: str
    span_ids: list[str]                        # kaynak birimlerin span-id'leri (atıf)
    doc_id: str
    sinif: str
    ders: str
    kaynak_turu: str
    page_start: int
    page_end: int
    kinds: list[str]
    page_visual: str                           # baskın görsel sınıfı
    approx_tokens: int
    parent_id: str | None = None               # child için
    child_ids: list[str] = field(default_factory=list)  # parent için


def _mk(units: list[CanonicalUnit], doc: CanonicalDoc, level: str, n: int) -> Chunk:
    text = "\n".join(u.text for u in units)
    pages = [u.page for u in units]
    vis = Counter(u.page_visual for u in units).most_common(1)[0][0]
    return Chunk(
        chunk_id=f"{doc.doc_id}:{'c' if level=='child' else 'p'}{n}",
        level=level, text=text, span_ids=[u.span_id for u in units],
        doc_id=doc.doc_id, sinif=doc.sinif, ders=doc.ders, kaynak_turu=doc.kaynak_turu,
        page_start=min(pages), page_end=max(pages),
        kinds=sorted({u.kind for u in units}), page_visual=vis,
        approx_tokens=approx_tokens(text))


def chunk_document(doc: CanonicalDoc, *, page_aligned: bool | None = None) -> list[Chunk]:
    """CanonicalDoc → child + parent chunk'lar (başlık sınırlarına saygılı).

    `page_aligned=True` iken her **child** chunk tek bir sayfaya bağlanır
    (sayfa değişiminde zorunlu flush) → `page_start == page_end`. Parent'lar
    bilerek sayfa aşar: onlar bağlam genişletme içindir, atıf kaynağı değil
    (parent'ın atıfı ayrı bir hata, bkz. #54).
    """
    if page_aligned is None:
        page_aligned = PAGE_ALIGNED_DEFAULT
    units = doc.retrievable_units

    # --- çocuk chunk'lar ---
    children: list[Chunk] = []
    buf: list[CanonicalUnit] = []
    tok = 0
    cn = 0

    def flush_child():
        nonlocal buf, tok, cn
        if buf:
            children.append(_mk(buf, doc, "child", cn)); cn += 1
            buf = []; tok = 0

    for u in units:
        # #53: sayfa degisimi ZORUNLU sinir -- baslik kuralindan farkli olarak
        # doluluk sartina baglanmaz, yoksa asma yine olur.
        if page_aligned and buf and u.page != buf[-1].page:
            flush_child()
        # başlık yeni bölüm başlatır — ama yalnız çocuk zaten yeterince doluysa
        # (aksi halde küçük bloklu + çok-başlıklı kitapta chunk'lar minik kalır).
        if u.kind == HEADING and tok >= CHILD_MIN:
            flush_child()
        buf.append(u)
        tok += approx_tokens(u.text)
        if tok >= CHILD_FLUSH:
            flush_child()
    flush_child()

    # --- üst chunk'lar (çocukları grupla; başlıkla başlayan çocuk yeni bölüm) ---
    parents: list[Chunk] = []
    pbuf: list[Chunk] = []
    ptok = 0
    pn = 0

    def flush_parent():
        nonlocal pbuf, ptok, pn
        if pbuf:
            # parent metni = çocuk metinleri; span_id'ler birleşik
            merged_units_text = "\n".join(c.text for c in pbuf)
            span_ids = [sid for c in pbuf for sid in c.span_ids]
            pages = [p for c in pbuf for p in (c.page_start, c.page_end)]
            vis = Counter(c.page_visual for c in pbuf).most_common(1)[0][0]
            pid = f"{doc.doc_id}:p{pn}"
            parents.append(Chunk(
                chunk_id=pid, level="parent", text=merged_units_text, span_ids=span_ids,
                doc_id=doc.doc_id, sinif=doc.sinif, ders=doc.ders, kaynak_turu=doc.kaynak_turu,
                page_start=min(pages), page_end=max(pages),
                kinds=sorted({k for c in pbuf for k in c.kinds}), page_visual=vis,
                approx_tokens=approx_tokens(merged_units_text),
                child_ids=[c.chunk_id for c in pbuf]))
            for c in pbuf:
                c.parent_id = pid
            pbuf = []; ptok = 0; pn += 1

    for c in children:
        # başlıkla başlayan çocuk yeni bölümdür — ama yalnız üst zaten dolmuşsa böl
        starts_section = HEADING in c.kinds
        if starts_section and ptok >= PARENT_MIN:
            flush_parent()
        pbuf.append(c)
        ptok += c.approx_tokens
        if ptok >= PARENT_FLUSH:
            flush_parent()
    flush_parent()

    return children + parents


def to_dicts(chunks: list[Chunk]) -> list[dict]:
    return [asdict(c) for c in chunks]
