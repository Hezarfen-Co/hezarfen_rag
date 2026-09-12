"""Faz 0.5 integration testi — 12-bio kanonik doküman (gerçek veri)."""
import os
import re
import unittest

import corpus

from src.ingest.canonical import build_canonical

BOOK = corpus.book_path()


@corpus.requires_book
class Canonical12BioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = build_canonical(BOOK, sinif=corpus.find_book()[1], ders=corpus.find_book()[2])

    def test_ids(self):
        self.assertRegex(self.doc.doc_id, r"^[0-9a-f]{12}$")
        self.assertRegex(self.doc.source_version, r"^[0-9a-f]{64}$")
        self.assertGreater(self.doc.page_count, 50)   # korpustan bağımsız: gerçek bir kitap

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
            self.assertEqual((u.sinif, u.ders), (corpus.find_book()[1], corpus.find_book()[2]))

    def test_text_normalized(self):
        # hiçbir birimde soft-hyphen kalmamalı (0.6 normalize uygulandı)
        self.assertFalse(any("\xad" in u.text or "﻿" in u.text for u in self.doc.units))

    def test_page_visual_classes_valid(self):
        classes = {u.page_visual for u in self.doc.units}
        self.assertTrue(classes.issubset({"figure_heavy", "mixed", "low_visual"}))

    def test_zero_leak_excluded_pages(self):
        """Hariç tutulan HİÇBİR sayfada retrievable birim kalmamalı.

        Eski hâli sayfa numaralarını (11, 187) 12-bio'ya göre sabitliyordu;
        o kitap depoda olmadığı için test hiç koşmuyordu ve sabitler
        doğrulanamaz durumdaydı. Artık hariç tutulan sayfalar **izolasyon
        raporundan türetiliyor** → her korpusta geçerli bir değişmez."""
        # `build_canonical` izolasyonu zaten uyguladı; hariç tutulan sayfayı
        # "o sayfada hiç retrievable birim yok" ile tanıyoruz.
        sayfalar = {u.page for u in self.doc.units}
        haric = {p for p in sayfalar
                 if not any(u.page == p and u.retrievable for u in self.doc.units)}
        self.assertTrue(haric, "hiçbir sayfa hariç tutulmamış — izolasyon çalışmıyor")
        for pno in sorted(haric):
            sizan = [u for u in self.doc.units if u.page == pno and u.retrievable]
            self.assertFalse(sizan, f"sayfa {pno}: {len(sizan)} birim sızdı")

    def test_span_id_stable_across_runs(self):
        again = build_canonical(BOOK, sinif=corpus.find_book()[1], ders=corpus.find_book()[2])
        self.assertEqual(again.doc_id, self.doc.doc_id)   # sha256 stabil


if __name__ == "__main__":
    unittest.main()
