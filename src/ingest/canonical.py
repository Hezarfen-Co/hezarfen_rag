"""Faz 0.5 — Kanonik doküman şeması + metadata.

parse (0.3a/b) + izolasyon (0.4) + TR-normalize (0.6) + görsel sınıfı (0.3d) tek
**chunk'lanabilir** yapıda birleşir. Her birim **versiyonlu, stabil span-id** taşır
(claim–evidence sözleşmesinin temeli: her iddia sabit kaynak span'ına bağlanacak,
bkz. mimari §0.1 + RES-001). Tablo (0.3c) opsiyonel (pdfplumber yavaş).

span_id = "<doc_id>#<sayfa>.<blok_no>"  ·  doc_id = dosya sha256'sının ilk 12'si
(kaynak değişirse sha256 → doc_id → span_id değişir = sürümleme).
"""
from __future__ import annotations
import hashlib
import json
import os
from dataclasses import dataclass, asdict, field

from .pdf_parse import parse_pdf, ParsedDoc
from .isolate import apply_isolation
from .visuals import analyze_document
from ..text import normalize


@dataclass
class CanonicalUnit:
    span_id: str                               # versiyonlu, stabil (atıf birimi)
    doc_id: str
    sinif: str
    ders: str
    kaynak_turu: str                           # ders_kitabi / konu_ozeti / defter ...
    page: int
    bbox: tuple[float, float, float, float]
    block_no: int
    kind: str                                  # heading/paragraph/list/caption...
    text: str                                  # TR-normalize edilmiş
    page_visual: str                           # figure_heavy/mixed/low_visual
    retrieval_disi: bool                       # sızıntı: indekse girmez

    @property
    def retrievable(self) -> bool:
        return not self.retrieval_disi


@dataclass
class CanonicalDoc:
    source_path: str
    doc_id: str
    source_version: str                        # tam sha256
    sinif: str
    ders: str
    kaynak_turu: str
    page_count: int
    units: list[CanonicalUnit] = field(default_factory=list)

    @property
    def retrievable_units(self) -> list[CanonicalUnit]:
        return [u for u in self.units if u.retrievable]

    @property
    def summary(self) -> dict:
        return {"total": len(self.units),
                "retrievable": len(self.retrievable_units),
                "excluded": sum(1 for u in self.units if u.retrieval_disi)}


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_span_id(doc_id: str, page: int, block_no: int) -> str:
    return f"{doc_id}#{page}.{block_no}"


def units_from_parsed(doc: ParsedDoc, *, doc_id: str, sinif: str, ders: str,
                      kaynak_turu: str, page_visual: dict[int, str]) -> list[CanonicalUnit]:
    """İzole edilmiş+parse edilmiş dokümandan kanonik birimler (metin normalize edilir).
    Saf fonksiyon — sentetik ParsedDoc ile test edilebilir."""
    out: list[CanonicalUnit] = []
    for p in doc.pages:
        for b in p.blocks:
            if not b.is_body:            # header/footer/label indekslenmez
                continue
            text = normalize(b.text)
            if not text:
                continue
            out.append(CanonicalUnit(
                span_id=make_span_id(doc_id, b.page, b.block_no),
                doc_id=doc_id, sinif=sinif, ders=ders, kaynak_turu=kaynak_turu,
                page=b.page, bbox=b.bbox, block_no=b.block_no, kind=b.kind,
                text=text, page_visual=page_visual.get(b.page, "low_visual"),
                retrieval_disi=b.retrieval_disi))
    return out


def build_canonical(path: str, sinif: str, ders: str, *,
                    kaynak_turu: str = "ders_kitabi", ocr: bool = False,
                    vlm: bool = False, captioner=None, distill: bool = False) -> CanonicalDoc:
    """PDF → kanonik doküman (parse + izolasyon + normalize + görsel sınıfı + metadata).

    `ocr=True` (Faz 0.8): text-layer'ı boş taranmış/görüntü sayfalar Tesseract ile
    OCR edilir (bkz. pdf_parse.parse_pdf). Varsayılan KAPALI.
    `vlm=True` (Faz 5, #23): figure_heavy sayfalar VLM ile captionlanıp
    `kind="gorsel_aciklama"` birim olarak eklenir (bkz. visual_caption.py; captioner
    verilmezse env'den VLMCaptioner denenir, kullanılamıyorsa zarifçe atlanır)."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    full = file_sha256(path)
    doc_id = full[:12]
    parsed = parse_pdf(path, ocr=ocr)
    apply_isolation(parsed)                                  # retrieval_disi işaretle
    vis = analyze_document(path)
    page_visual = {pv.page: pv.klass for pv in vis["pages"]}
    units = units_from_parsed(parsed, doc_id=doc_id, sinif=sinif, ders=ders,
                              kaynak_turu=kaynak_turu, page_visual=page_visual)
    if distill:                                          # #8: tekrar/near-duplicate ayıkla
        from .distill import distill_units
        units, _ = distill_units(units)
    if vlm:
        from .visual_caption import caption_visual_units, merge_visual_units
        if captioner is None:
            from ..providers.vlm import default_captioner
            captioner = default_captioner()
        vunits = caption_visual_units(path, doc_id=doc_id, sinif=sinif, ders=ders,
                                      kaynak_turu=kaynak_turu, page_visual=page_visual,
                                      captioner=captioner)
        units = merge_visual_units(units, vunits)
    return CanonicalDoc(source_path=path, doc_id=doc_id, source_version=full,
                        sinif=sinif, ders=ders, kaynak_turu=kaynak_turu,
                        page_count=parsed.page_count, units=units)


def to_json(doc: CanonicalDoc) -> str:
    return json.dumps({
        "source_path": doc.source_path, "doc_id": doc.doc_id,
        "source_version": doc.source_version, "sinif": doc.sinif, "ders": doc.ders,
        "kaynak_turu": doc.kaynak_turu, "page_count": doc.page_count,
        "summary": doc.summary,
        "units": [asdict(u) for u in doc.units],
    }, ensure_ascii=False)


def save_json(doc: CanonicalDoc, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(to_json(doc))
