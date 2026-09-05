"""Faz 5 (#23) — görsel içerik captioning ingest pass.

`analyze_document` (visuals.py) figure_heavy işaretlediği sayfalar VLM ile Türkçe
betimlenir → `kind="gorsel_aciklama"` CanonicalUnit (gerçek span_id: sayfa+bbox).
Böylece görsel içerik mevcut metin boru hattında (embed→retrieve→rerank→generate→
özet) aranır/özetlenir + atıf gerçek görsele çözülür. OCR (gömülü metin) ile
tamamlayıcıdır: OCR yazıyı, captioning ŞEKLİ/DİYAGRAMI kurtarır.

Zarif degradasyon: captioner yoksa/kullanılamıyorsa boş liste (çağıran metinle devam).
Maliyet: yalnız figure_heavy sayfa başına 1 VLM çağrısı (default-off, `build_canonical(vlm=True)`).
"""
from __future__ import annotations

import fitz

from .canonical import CanonicalUnit, make_span_id
from ..text import normalize

VISUAL_KIND = "gorsel_aciklama"
_VISUAL_BLOCK_NO = 8000          # görsel-birim blok no (metin bloklarıyla çakışmaz)


def target_visual_pages(page_visual: dict[int, str],
                        classes: tuple[str, ...] = ("figure_heavy",)) -> list[int]:
    """Captionlanacak sayfalar (varsayılan: yalnız figure_heavy — maliyet sınırı)."""
    return sorted(p for p, k in page_visual.items() if k in classes)


def merge_visual_units(text_units: list[CanonicalUnit],
                       visual_units: list[CanonicalUnit]) -> list[CanonicalUnit]:
    """Görsel-birimleri, her birini KENDİ sayfasının son metin biriminden SONRA
    yerleştirerek okuma sırasını korur (saf fonksiyon — VLM'siz test edilebilir).
    Metin biriminin olmadığı görsel-sayfaların birimleri sona eklenir."""
    if not visual_units:
        return text_units
    vby: dict[int, list[CanonicalUnit]] = {}
    for v in visual_units:
        vby.setdefault(v.page, []).append(v)
    merged: list[CanonicalUnit] = []
    for i, u in enumerate(text_units):
        merged.append(u)
        next_page = text_units[i + 1].page if i + 1 < len(text_units) else None
        if u.page != next_page and u.page in vby:
            merged.extend(vby.pop(u.page))
    for p in sorted(vby):            # metinsiz görsel-sayfalar
        merged.extend(vby[p])
    return merged


def caption_visual_units(path: str, *, doc_id: str, sinif: str, ders: str,
                         kaynak_turu: str, page_visual: dict[int, str], captioner,
                         classes: tuple[str, ...] = ("figure_heavy",),
                         dpi: int = 200) -> list[CanonicalUnit]:
    """figure_heavy sayfaları VLM ile captionlar → CanonicalUnit listesi.
    captioner None/kullanılamaz ise boş liste (zarif degradasyon)."""
    if captioner is None or not captioner.available():
        return []
    targets = set(target_visual_pages(page_visual, classes))
    if not targets:
        return []
    out: list[CanonicalUnit] = []
    doc = fitz.open(path)
    try:
        for page in doc:
            pno = page.number + 1
            if pno not in targets:
                continue
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
            text = normalize(captioner.caption(pix.tobytes("png")))
            if not text:
                continue
            rect = page.rect
            out.append(CanonicalUnit(
                span_id=make_span_id(doc_id, pno, _VISUAL_BLOCK_NO),
                doc_id=doc_id, sinif=sinif, ders=ders, kaynak_turu=kaynak_turu,
                page=pno, bbox=(0.0, 0.0, rect.width, rect.height),
                block_no=_VISUAL_BLOCK_NO, kind=VISUAL_KIND, text=text,
                page_visual=page_visual.get(pno, "figure_heavy"), retrieval_disi=False))
    finally:
        doc.close()
    return out
