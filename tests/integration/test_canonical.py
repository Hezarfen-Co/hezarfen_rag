"""Faz 0.5 integration testi — 12-bio kanonik doküman (gerçek veri)."""
import os
import re
import unittest

from src.ingest.canonical import build_canonical

BOOK = os.path.join("data", "lise", "12", "biyoloji", "kitap.pdf")


@unittest.skipUnless(os.path.exists(BOOK), f"veri yok: {BOOK}")
class Canonical12BioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = build_canonical(BOOK, sinif="12", ders="biyoloji")

    def test_ids(self):
        self.assertRegex(self.doc.doc_id, r"^[0-9a-f]{12}$")
        self.assertRegex(self.doc.source_version, r"^[0-9a-f]{64}$")
        self.assertEqual(self.doc.page_count, 187)

    def test_units_and_isolation(self):
        s = self.doc.summary
        self.assertGreater(s["total"], 100)
        self.assertGreater(s["retrievable"], 0)
        self.assertLess(s["retrievable"], s["total"])   # izolasyon bazı birimleri hariç tuttu
        self.assertEqual(s["retrievable"] + s["excluded"], s["total"])

    def test_every_unit_has_provenance(self):
        for u in self.doc.units[:200]:
            self.assertTrue(u.span_id.startswith(self.doc.doc_id + "#"))
            self.assertTrue(u.text.strip())
            x0, y0, x1, y1 = u.bbox
            self.assertLess(x0, x1); self.assertLess(y0, y1)
            self.assertEqual((u.sinif, u.ders), ("12", "biyoloji"))

    def test_text_normalized(self):
        # hiçbir birimde soft-hyphen kalmamalı (0.6 normalize uygulandı)
        self.assertFalse(any("\xad" in u.text or "﻿" in u.text for u in self.doc.units))

    def test_page_visual_classes_valid(self):
        classes = {u.page_visual for u in self.doc.units}
        self.assertTrue(classes.issubset({"figure_heavy", "mixed", "low_visual"}))

    def test_zero_leak_excluded_pages(self):
        # 12-bio'da 187 (kaynakça) ve 11 (kitap tanıtımı) hariç → o sayfada retrievable birim olmamalı
        for pno in (11, 187):
            self.assertFalse(any(u.page == pno and u.retrievable for u in self.doc.units),
                             f"sayfa {pno}'de sızan birim var")

    def test_span_id_stable_across_runs(self):
        again = build_canonical(BOOK, sinif="12", ders="biyoloji")
        self.assertEqual(again.doc_id, self.doc.doc_id)   # sha256 stabil


if __name__ == "__main__":
    unittest.main()
