"""Faz 0.4 integration testi — 12-bio gerçek sızıntı izolasyonu (0 sızıntı kapısı)."""
import os
import unittest

from src.ingest import parse_pdf
from src.ingest.isolate import apply_isolation

BOOK = os.path.join("data", "lise", "12", "biyoloji", "kitap.pdf")


@unittest.skipUnless(os.path.exists(BOOK), f"veri yok: {BOOK}")
class Isolation12BioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = parse_pdf(BOOK)
        cls.rep = apply_isolation(cls.doc)

    def test_front_and_back_matter_excluded(self):
        pages = {e["page"]: e["reason"] for e in self.rep["excluded_pages"]}
        self.assertIn(11, pages)                       # kitap tanıtımı (ön-madde)
        self.assertIn(187, pages)                      # kaynakça (arka-madde)
        self.assertEqual(pages[187], "kaynakca")

    def test_teaching_page_retained(self):
        # sayfa 41 öğretici → hariç değil, indekslenebilir bloğu olmalı
        p41 = self.doc.pages[40]
        self.assertTrue(any(b.retrievable for b in p41.blocks))

    def test_scattered_question_blocks_flagged(self):
        self.assertGreater(self.rep["assessment_excluded_blocks"], 0)

    def test_retrievable_subset_of_total(self):
        self.assertGreater(self.rep["retrievable_blocks"], 0)
        self.assertLess(self.rep["retrievable_blocks"], self.rep["total_blocks"])

    def test_zero_leak_no_retrievable_on_excluded_page(self):
        # 0-SIZINTI: hariç sayfada indekslenebilir blok KALMAMALI
        excl = {e["page"] for e in self.rep["excluded_pages"]}
        for p in self.doc.pages:
            if p.number in excl:
                self.assertFalse(any(b.retrievable for b in p.blocks),
                                 f"hariç sayfa {p.number}'de sızan blok var")


if __name__ == "__main__":
    unittest.main()
