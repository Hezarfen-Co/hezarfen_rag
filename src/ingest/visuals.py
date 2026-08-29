"""Faz 0.3d — Görsel/şekil analizi (PyMuPDF).

Amaç: her sayfanın **görsel yoğunluğunu** ölçüp sınıflamak → hangi sayfa/içerik
VLM'e (DeepSeek-vision) gitmeli (pahalı), hangisi düz metinle yeter (ucuz).
Böylece dil modeli verimli kullanılır ve RAG doğru beslenir.

Gerçek 12-bio bulgusu:
- Diyagramlar **vektör kompozit** (medyan ~14, max ~3251 parça/sayfa) → embedded
  image ÇEKİLMEZ; şekil bölgesi **render** edilerek VLM'e verilir.
- Alan-toplamı üst üste binen parçalarda >%100 verir → **union (grid) kaplama** kullanılır.

Kullanım:
    from src.ingest.visuals import analyze_document, render_region
    prof = analyze_document("data/lise/12/biyoloji/kitap.pdf")
    print(prof["summary"])            # figür-ağırlıklı/karma/salt-metin dağılımı
    png = render_region(page, bbox)   # şekil bölgesini PNG'ye (VLM için)
"""
from __future__ import annotations
import os
from dataclasses import dataclass

import fitz

# Sınıf eşikleri (union görsel kaplama)
FIGURE_HEAVY = 0.40    # ≥ → VLM/crop şart
LOW_VISUAL = 0.10      # < → düz metin yeter; arası "karma"

FIGURE = "figure_heavy"
MIXED = "mixed"
TEXT = "low_visual"


@dataclass
class PageVisual:
    page: int
    n_fragments: int          # görsel parça sayısı (vektör kompozit göstergesi)
    image_coverage: float     # union görsel kaplama (0..1)
    text_coverage: float      # union metin kaplama (0..1)
    klass: str                # figure_heavy | mixed | low_visual


def _grid_coverage(rects: list[tuple], W: float, H: float, gx: int = 40) -> float:
    """Dikdörtgenlerin BİRLEŞİM (union) kaplaması — grid ile (üst üste binmeyi saymaz)."""
    if not rects or W <= 0 or H <= 0:
        return 0.0
    gy = max(1, round(gx * H / W))
    cw, ch = W / gx, H / gy
    grid = bytearray(gx * gy)
    for (x0, y0, x1, y1) in rects:
        if x1 <= x0 or y1 <= y0:
            continue
        cx0 = max(0, int(x0 // cw)); cx1 = min(gx - 1, int((x1 - 1e-6) // cw))
        cy0 = max(0, int(y0 // ch)); cy1 = min(gy - 1, int((y1 - 1e-6) // ch))
        for cy in range(cy0, cy1 + 1):
            base = cy * gx
            for cx in range(cx0, cx1 + 1):
                grid[base + cx] = 1
    return sum(grid) / (gx * gy)


def _classify(image_cov: float) -> str:
    if image_cov >= FIGURE_HEAVY:
        return FIGURE
    if image_cov < LOW_VISUAL:
        return TEXT
    return MIXED


def page_visual(page, number: int) -> PageVisual:
    W, H = page.rect.width, page.rect.height
    irects = [tuple(im["bbox"]) for im in page.get_image_info()]
    trects = [tuple(b[:4]) for b in page.get_text("blocks") if b[6] == 0]
    icov = _grid_coverage(irects, W, H)
    tcov = _grid_coverage(trects, W, H)
    return PageVisual(page=number, n_fragments=len(irects),
                      image_coverage=round(icov, 3), text_coverage=round(tcov, 3),
                      klass=_classify(icov))


def analyze_document(path: str) -> dict:
    """Tüm sayfaların görsel profili + toplam özet (RAG yönlendirme/maliyet için)."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    doc = fitz.open(path)
    try:
        pages = [page_visual(p, i + 1) for i, p in enumerate(doc)]
    finally:
        doc.close()
    n = len(pages) or 1
    counts = {FIGURE: 0, MIXED: 0, TEXT: 0}
    for pv in pages:
        counts[pv.klass] += 1
    return {
        "source_path": path,
        "page_count": len(pages),
        "pages": pages,
        "summary": {
            "figure_heavy": counts[FIGURE], "mixed": counts[MIXED],
            "low_visual": counts[TEXT],
            "figure_heavy_pct": round(counts[FIGURE] / n, 3),
            "avg_image_coverage": round(sum(p.image_coverage for p in pages) / n, 3),
            "median_fragments": sorted(p.n_fragments for p in pages)[len(pages) // 2] if pages else 0,
        },
    }


def render_region(page, bbox: tuple[float, float, float, float], dpi: int = 150) -> bytes:
    """Şekil bölgesini PNG'ye render et (VLM'e verilecek doğru temsil — vektör
    kompozit diyagramlar embedded image olarak çekilemediği için)."""
    clip = fitz.Rect(*bbox)
    pix = page.get_pixmap(clip=clip, dpi=dpi)
    return pix.tobytes("png")
