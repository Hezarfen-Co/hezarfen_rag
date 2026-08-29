"""Faz 0.3a integration testi — 12-bio kitabını gerçek veri üzerinde parse et.

Veri (`data/`) git-ignored ve büyük olduğundan, yoksa test ATLANIR (temiz
checkout'ta kırılmaz). Veri varsa: 187 sayfa + metin bütünlüğü doğrulanır.
"""
import os
import unittest

from src.ingest import parse_pdf

BOOK = os.path.join("data", "lise", "12", "biyoloji", "kitap.pdf")


@unittest.skipUnless(os.path.exists(BOOK), f"veri yok: {BOOK} (indirilmemiş)")
class PdfParse12BioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = parse_pdf(BOOK)

    def test_page_count_187(self):
        self.assertEqual(self.doc.page_count, 187)
        self.assertEqual(len(self.doc.pages), 187)

    def test_has_nonempty_text(self):
        # Kitabın büyük çoğunluğu metin içermeli
        with_text = sum(1 for p in self.doc.pages if p.text.strip())
        self.assertGreater(with_text, 150, "çok az sayfada metin var — parse şüpheli")

    def test_blocks_have_valid_bbox(self):
        # İlk metinli sayfada bbox tutarlı olmalı (atıf için şart)
        page = next(p for p in self.doc.pages if p.blocks)
        b = page.blocks[0]
        x0, y0, x1, y1 = b.bbox
        self.assertLess(x0, x1)
        self.assertLess(y0, y1)
        self.assertEqual(b.page, page.number)

    def test_total_text_substantial(self):
        self.assertGreater(len(self.doc.text), 50_000, "toplam metin beklenenden az")


if __name__ == "__main__":
    unittest.main()
