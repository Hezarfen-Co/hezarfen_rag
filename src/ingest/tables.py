"""Faz 0.3c — Tablo tespiti (pdfplumber) + sıkı kalite filtresi.

Gerçek 12-bio bulgusu: ham `find_tables` çoğunlukla **dekoratif kutu**yu tablo
sanıyor (270 ham → 21 gerçek). Bu yüzden kalite filtresi ŞART: yeterli
satır/sütun + dolu-hücre oranı olmayan "tablolar" elenir. Yalnız yüksek-güven
tablolar döner; her biri sayfa/bbox ile atıflanabilir.

Kullanım:
    from src.ingest.tables import extract_tables
    tbls = extract_tables("data/lise/12/biyoloji/kitap.pdf", pages=[12])
    for t in tbls[12]:
        print(t.n_rows, t.n_cols, t.fill_ratio, t.rows[0])
"""
from __future__ import annotations
import os
import warnings
from dataclasses import dataclass, field

import pdfplumber

Rows = list[list[str | None]]


@dataclass
class Table:
    page: int                                  # 1-indeksli
    bbox: tuple[float, float, float, float]
    rows: Rows
    n_rows: int
    n_cols: int
    fill_ratio: float


def fill_ratio(rows: Rows) -> float:
    cells = [c for r in rows for c in r]
    if not cells:
        return 0.0
    return sum(1 for c in cells if c and str(c).strip()) / len(cells)


def is_real_table(rows: Rows, *, min_rows: int = 2, min_cols: int = 2,
                  min_cells: int = 6, min_fill: float = 0.6) -> bool:
    """Dekoratif kutuyu gerçek tablodan ayır. Eşikler ayarlanabilir; varsayılan
    filtre 12-bio'nun %0-25 dolu dekoratif kutularını eler."""
    n_rows = len(rows)
    n_cols = max((len(r) for r in rows), default=0)
    if n_rows < min_rows or n_cols < min_cols or n_rows * n_cols < min_cells:
        return False
    return fill_ratio(rows) >= min_fill


def extract_tables(path: str, pages: list[int] | None = None, *,
                   min_fill: float = 0.6) -> dict[int, list[Table]]:
    """PDF'den gerçek tabloları çıkar. pages=None → tüm kitap (yavaş);
    pages=[12,20] → yalnız o sayfalar (hızlı; ingest/test için). 1-indeksli."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    out: dict[int, list[Table]] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pdfplumber.open(path) as pdf:
            if pages is None:
                targets = list(range(len(pdf.pages)))
            else:
                targets = [p - 1 for p in pages if 1 <= p <= len(pdf.pages)]
            for idx in targets:
                page = pdf.pages[idx]
                real: list[Table] = []
                for t in page.find_tables():
                    rows = t.extract()
                    if not is_real_table(rows, min_fill=min_fill):
                        continue
                    real.append(Table(
                        page=idx + 1, bbox=tuple(round(x, 1) for x in t.bbox),
                        rows=rows, n_rows=len(rows),
                        n_cols=max((len(r) for r in rows), default=0),
                        fill_ratio=round(fill_ratio(rows), 3)))
                if real:
                    out[idx + 1] = real
    return out
