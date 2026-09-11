"""Korpus edinme — kaynak materyalleri dış sistemlerden getirme.

`src/ingest/` ile karıştırılmamalı: orası bir PDF'i kanonik belgeye ÇEVİRİR
(parse, OCR, tablo, görsel); burası o PDF'lerin nereden ve nasıl GELDİĞİdir.
İki iş ayrı: biri ağa ve kaynak sitenin biçimine, diğeri belge yapısına bağlı.
"""
from .eba_catalog import Material, catalog, parse_bundle, summary

__all__ = ["Material", "catalog", "parse_bundle", "summary"]
