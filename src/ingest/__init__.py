"""Kaynak derleyici: PDF/görsel → yapılandırılmış, atıflanabilir öğeler.

Faz 0 (veri hijyeni): pdf_parse (metin blokları + koordinat), sonra tablo,
yasaklı-sayfa izolasyonu, metadata, curriculum graph. Bkz. Obsidian [[plan]].
"""
from .pdf_parse import Block, Page, ParsedDoc, parse_pdf
from .tables import Table, extract_tables, is_real_table

__all__ = ["Block", "Page", "ParsedDoc", "parse_pdf",
           "Table", "extract_tables", "is_real_table"]
