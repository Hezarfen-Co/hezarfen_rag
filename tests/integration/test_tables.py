"""Faz 0.3c integration testi — gerçek 12-bio'da tablo tespiti + filtre.
Hız için YALNIZ birkaç sayfa taranır (tüm kitap pdfplumber'da yavaş)."""
import os
import unittest

from src.ingest.tables import extract_tables

BOOK = os.path.join("data", "lise", "12", "biyoloji", "kitap.pdf")


@unittest.skipUnless(os.path.exists(BOOK), f"veri yok: {BOOK}")
class TableExtractionTests(unittest.TestCase):
    def test_decorative_page1_filtered(self):
        # Sayfa 1 = kapak; dekoratif kutular gerçek tablo sayılmamalı
        out = extract_tables(BOOK, pages=[1])
        self.assertEqual(out.get(1, []), [], "kapak kutusu gerçek tablo sayıldı (filtre zayıf)")

    def test_page12_icon_box_filtered(self):
        # Sayfa 12 = güvenlik ikon kutusu (9x2, %50 dolu) → GERÇEK tablo değil, elenir
        out = extract_tables(BOOK, pages=[12])
        self.assertEqual(out.get(12, []), [], "ikon kutusu (%50 dolu) gerçek tablo sayıldı")

    def test_page20_has_real_dna_rna_table(self):
        # Sayfa 20 = gerçek DNA/RNA karşılaştırma tablosu (5x2, %100 dolu)
        out = extract_tables(BOOK, pages=[20])
        tabs = out.get(20, [])
        self.assertTrue(tabs, "sayfa 20'de gerçek tablo bulunamadı")
        t = tabs[0]
        self.assertGreaterEqual(t.fill_ratio, 0.6)
        self.assertEqual(t.page, 20)
        flat = " ".join(str(c) for r in t.rows for c in r if c)
        self.assertIn("DNA", flat)
        self.assertIn("RNA", flat)
        x0, y0, x1, y1 = t.bbox           # bbox tutarlı (atıf için)
        self.assertLess(x0, x1)
        self.assertLess(y0, y1)


if __name__ == "__main__":
    unittest.main()
