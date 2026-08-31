"""Faz 0.3a/b — Native PDF parse (PyMuPDF).

0.3a: sayfa → metin blokları + koordinat (bbox) + sayfa no (atıf/provenance).
0.3b: her bloğa **font boyutu** + **tip** (heading/paragraph/list/caption/header/
      footer/label) + **sütun-farkında okuma sırası** (2 sütunlu ders kitabı).

Tasarım gerçek 12-bio düzenine göre (2 sütun: gövde sol ~57-397, yan sağ ~405-504;
başlık font'u gövdeden büyük; üst çalışan-başlık + alt sayfa no; diyagram etiketi
gürültüsü). Tablo = 0.3c, görsel = Faz 5 ayrı ele alınır.
"""
from __future__ import annotations
import json
import os
import re
import statistics
from dataclasses import dataclass, asdict, field

import fitz  # PyMuPDF

# Blok tipleri
HEADING, PARAGRAPH, LIST, CAPTION, HEADER, FOOTER, LABEL = (
    "heading", "paragraph", "list", "caption", "header", "footer", "label")

_CAPTION_KW = ("görsel", "şekil", "tablo", "grafik", "resim", "harita")
_LIST_MARK = re.compile(r"^\s*(?:[•◦‣▪·\-–—*]|\(?\d{1,2}[\.\)]|[a-zçğıöşü]\))\s+")
_SECTION_NO = re.compile(r"^\s*(?:\d+\.){1,3}\s|^\s*[A-ZÇĞİÖŞÜ]\)\s")


@dataclass
class Block:
    """Bir sayfadaki metin bloğu + koordinatı + font + tip (atıf/yapı için)."""
    page: int                                 # 1-indeksli sayfa no
    bbox: tuple[float, float, float, float]   # (x0, y0, x1, y1)
    text: str
    block_no: int                             # PyMuPDF sayfa-içi blok no
    font_size: float = 0.0                    # bloğun baskın (max) font boyutu
    kind: str = PARAGRAPH                      # yukarıdaki tiplerden
    retrieval_disi: bool = False              # sızıntı: soru/cevap/meta → indekslenmez (bkz. isolate.py)

    @property
    def is_body(self) -> bool:
        """Retrieval/özet için asıl öğretici metin mi (header/footer/label değil)."""
        return self.kind in (HEADING, PARAGRAPH, LIST, CAPTION)

    @property
    def retrievable(self) -> bool:
        """İndekse girer mi: öğretici gövde VE sızıntı-dışı."""
        return self.is_body and not self.retrieval_disi


@dataclass
class Page:
    number: int
    width: float
    height: float
    blocks: list[Block] = field(default_factory=list)  # okuma sırasında

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)

    @property
    def body_text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.is_body)


@dataclass
class ParsedDoc:
    source_path: str
    page_count: int
    pages: list[Page] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


# ------------------------------- sınıflandırma -------------------------------

def _strip_marker(text: str) -> str:
    # Kitap görsellerinde "W  Görsel 1.9: ..." gibi öncü işaret var; temizle
    return re.sub(r"^\s*[WQ-]\s+", "", text).strip()


def classify(text: str, font_size: float, bbox, page_h: float,
             body_size: float) -> str:
    """Bloğu tipe ayır. body_size = sayfanın gövde (paragraf) font medyanı."""
    x0, y0, x1, y1 = bbox
    t = text.strip()
    clean = _strip_marker(t)
    low = clean.lower()
    # header/footer: sayfanın en üst/alt %6'sı + kısa
    if y1 <= page_h * 0.07 and len(t) < 120:
        return HEADER
    if y0 >= page_h * 0.93 and len(t) < 60:
        return FOOTER
    # caption: "Görsel/Şekil/Tablo..." ile başlar
    if any(low.startswith(k) for k in _CAPTION_KW):
        return CAPTION
    # heading: font gövdeden belirgin büyük (büyük font her şeyden önce gelir)
    if font_size >= body_size * 1.12 and len(t) < 140:
        return HEADING
    # list: satırların çoğu madde-işareti ile başlıyor (section-marker başlıktan ÖNCE,
    # yoksa "1. Adım / 2. Adım" numaralı liste başlık sanılır)
    lines = [ln for ln in t.splitlines() if ln.strip()]
    if lines and sum(bool(_LIST_MARK.match(ln)) for ln in lines) >= max(1, len(lines) // 2):
        return LIST
    # heading: bölüm-numarası deseni ("1.2.2. ..." veya "A) ...") + gövde-üstü font
    if _SECTION_NO.match(t) and font_size >= body_size and len(t) < 140:
        return HEADING
    # label: çok kısa, büyük-font olmayan → diyagram etiketi gürültüsü
    if len(clean) <= 14 and font_size < body_size * 1.12:
        return LABEL
    return PARAGRAPH


# ------------------------------- okuma sırası -------------------------------

def order_blocks(blocks: list[Block], page_width: float) -> list[Block]:
    """Sütun-farkında okuma sırası: header'lar önce → sol sütun (y) → sağ sütun (y)
    → footer'lar sonra. Tek sütunsa saf y-sıralaması."""
    headers = [b for b in blocks if b.kind == HEADER]
    footers = [b for b in blocks if b.kind == FOOTER]
    body = [b for b in blocks if b.kind not in (HEADER, FOOTER)]

    boundary = page_width * 0.5
    centers = [((b.bbox[0] + b.bbox[2]) / 2) for b in body]
    left = [b for b in body if (b.bbox[0] + b.bbox[2]) / 2 < boundary]
    right = [b for b in body if (b.bbox[0] + b.bbox[2]) / 2 >= boundary]
    # 2 sütun sayılması için iki taraf da anlamlı dolu olmalı (aksi halde tek sütun)
    two_col = len(left) >= 2 and len(right) >= 2

    def by_y(bs):
        return sorted(bs, key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))

    ordered = by_y(headers)
    if two_col:
        ordered += by_y(left) + by_y(right)
    else:
        ordered += by_y(body)
    ordered += by_y(footers)
    return ordered


# ------------------------------- parse -------------------------------

def _block_font_size(block: dict) -> float:
    sizes = [s["size"] for l in block.get("lines", []) for s in l.get("spans", [])]
    return max(sizes) if sizes else 0.0


def _block_text(block: dict) -> str:
    lines = []
    for l in block.get("lines", []):
        lines.append("".join(s["text"] for s in l.get("spans", [])))
    return "\n".join(lines).strip()


def parse_pdf(path: str) -> ParsedDoc:
    """PDF → sayfa (metin blokları + bbox + font + tip, okuma sırasında)."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    doc = fitz.open(path)
    try:
        pages: list[Page] = []
        for i, page in enumerate(doc):
            rect = page.rect
            raw = []  # (bbox, text, block_no, font_size)
            for bn, b in enumerate(page.get_text("dict").get("blocks", [])):
                if b.get("type") != 0:
                    continue
                text = _block_text(b)
                if not text:
                    continue
                raw.append((tuple(b["bbox"]), text, bn, _block_font_size(b)))
            # gövde font medyanı (uzun bloklar = paragraf)
            para_sizes = [fs for (_, t, _, fs) in raw if len(t) > 40] or \
                         [fs for (_, _, _, fs) in raw] or [10.0]
            body_size = statistics.median(para_sizes)
            blocks = []
            for bbox, text, bn, fs in raw:
                kind = classify(text, fs, bbox, rect.height, body_size)
                blocks.append(Block(page=i + 1, bbox=bbox, text=text,
                                    block_no=bn, font_size=round(fs, 2), kind=kind))
            blocks = order_blocks(blocks, rect.width)
            pages.append(Page(number=i + 1, width=rect.width,
                              height=rect.height, blocks=blocks))
        return ParsedDoc(source_path=path, page_count=doc.page_count, pages=pages)
    finally:
        doc.close()


def to_json(doc: ParsedDoc) -> str:
    return json.dumps({
        "source_path": doc.source_path, "page_count": doc.page_count,
        "pages": [{"number": p.number, "width": p.width, "height": p.height,
                   "blocks": [asdict(b) for b in p.blocks]} for p in doc.pages],
    }, ensure_ascii=False)


def save_json(doc: ParsedDoc, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(to_json(doc))
