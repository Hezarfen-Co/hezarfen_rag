"""Kaynak derleyici: PDF/görsel → yapılandırılmış, atıflanabilir öğeler.

Faz 0 (veri hijyeni): pdf_parse (metin blokları + koordinat), sonra tablo,
yasaklı-sayfa izolasyonu, metadata, curriculum graph. Bkz. Obsidian [[plan]].
"""
from .pdf_parse import Block, Page, ParsedDoc, parse_pdf
from .tables import Table, extract_tables, is_real_table
from .visuals import PageVisual, analyze_document, page_visual, render_region
from .isolate import apply_isolation, page_exclusion_reason
from .canonical import (CanonicalUnit, CanonicalDoc, build_canonical,
                        units_from_parsed, make_span_id, file_sha256)

__all__ = ["Block", "Page", "ParsedDoc", "parse_pdf",
           "Table", "extract_tables", "is_real_table",
           "PageVisual", "analyze_document", "page_visual", "render_region",
           "apply_isolation", "page_exclusion_reason",
           "CanonicalUnit", "CanonicalDoc", "build_canonical",
           "units_from_parsed", "make_span_id", "file_sha256"]
