"""Faz 0.3a — Native PDF parse (PyMuPDF).

Amaç: PDF'yi LLM'ye vermeden, deterministik olarak sayfa → **metin blokları +
koordinat (bbox) + sayfa no** çıkarmak. Her iddia sonra sayfa/bbox'a bağlanacağı
için koordinat baştan tutulur (atıf/provenance). Okuma sırası + blok tipi = 0.3b,
tablo = 0.3c ayrı adımlar.

Kullanım:
    from src.ingest import parse_pdf
    doc = parse_pdf("data/lise/12/biyoloji/kitap.pdf")
    print(doc.page_count, doc.pages[0].blocks[0].text)
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, asdict, field

import fitz  # PyMuPDF


@dataclass
class Block:
    """Bir sayfadaki metin bloğu + koordinatı (atıf için)."""
    page: int                    # 1-indeksli sayfa no
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    text: str
    block_no: int                # PyMuPDF'in sayfa-içi blok sırası (kaba okuma sırası)


@dataclass
class Page:
    number: int                  # 1-indeksli
    width: float
    height: float
    blocks: list[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


@dataclass
class ParsedDoc:
    source_path: str
    page_count: int
    pages: list[Page] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


def parse_pdf(path: str) -> ParsedDoc:
    """PDF'yi sayfa → metin blokları + bbox olarak ayrıştır. Görsel bloklar atlanır
    (tip 1); onlar Faz 5 multimodal'da ayrı ele alınır."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    doc = fitz.open(path)
    try:
        pages: list[Page] = []
        for i, page in enumerate(doc):
            rect = page.rect
            blocks: list[Block] = []
            # get_text("blocks"): (x0,y0,x1,y1, "text", block_no, block_type)
            # block_type 0 = metin, 1 = görsel. Sıralama kabaca yukarıdan aşağı.
            for b in page.get_text("blocks"):
                x0, y0, x1, y1, text, block_no, block_type = b[:7]
                if block_type != 0:
                    continue
                text = (text or "").strip()
                if not text:
                    continue
                blocks.append(Block(page=i + 1, bbox=(x0, y0, x1, y1),
                                    text=text, block_no=int(block_no)))
            pages.append(Page(number=i + 1, width=rect.width,
                              height=rect.height, blocks=blocks))
        return ParsedDoc(source_path=path, page_count=doc.page_count, pages=pages)
    finally:
        doc.close()


def to_json(doc: ParsedDoc) -> str:
    """Normalize JSON (Faz 0.5 kanonik şemanın çekirdeği)."""
    return json.dumps({
        "source_path": doc.source_path,
        "page_count": doc.page_count,
        "pages": [
            {"number": p.number, "width": p.width, "height": p.height,
             "blocks": [asdict(b) for b in p.blocks]}
            for p in doc.pages
        ],
    }, ensure_ascii=False)


def save_json(doc: ParsedDoc, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(to_json(doc))
