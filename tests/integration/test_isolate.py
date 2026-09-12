"""Faz 0.4 integration testi — 12-bio gerçek sızıntı izolasyonu (0 sızıntı kapısı)."""
import os
import unittest

import corpus

from src.ingest import parse_pdf
from src.ingest.isolate import apply_isolation

BOOK = corpus.book_path()


@corpus.requires_book
class Isolation12BioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = parse_pdf(BOOK)
        cls.rep = apply_isolation(cls.doc)

    def test_front_and_back_matter_excluded(self):
        """Ön/arka madde hariç tutulmalı — sayfa NUMARASI korpusa özgüdür.

        Eski hâli 11 ve 187'yi sabitliyordu (12-bio). Değişmez olan şu:
        (a) en az bir sayfa hariç tutulur, (b) sebepler tanınan kümeden gelir,
        (c) kaynakça/içindekiler gibi bölümler ilk ve son %15'lik dilimlerde
        yoğunlaşır."""
        pages = {e["page"]: e["reason"] for e in self.rep["excluded_pages"]}
        self.assertTrue(pages, "hiçbir sayfa hariç tutulmadı")
        tanınan = {"icindekiler", "kaynakca", "sozluk", "dizin", "onsoz",
                   "kitap_tanitimi", "kapak"}
        for sayfa, sebep in pages.items():
            self.assertIn(sebep, tanınan, f"sayfa {sayfa}: bilinmeyen sebep {sebep}")
        toplam = self.doc.page_count
        uclarda = [p for p in pages if p <= toplam * 0.15 or p >= toplam * 0.85]
        self.assertTrue(uclarda, "hariç tutulanların hiçbiri ön/arka maddede değil")

    def test_teaching_pages_are_retained(self):
        """Kitabın ORTA bölümü öğreticidir; hariç tutulmamalı.

        Eski hâli sayfa 41'i sabitliyordu. Değişmez: orta %50'lik dilimdeki
        sayfaların ezici çoğunluğu indekslenebilir blok taşımalı — aksi hâlde
        izolasyon fazla agresiftir ve içerik kaybediyoruz."""
        toplam = self.doc.page_count
        bas, son = int(toplam * 0.25), int(toplam * 0.75)
        orta = self.doc.pages[bas:son]
        dolu = [p for p in orta if any(b.retrievable for b in p.blocks)]
        self.assertGreater(len(dolu) / max(1, len(orta)), 0.7,
                           "orta bölümün %30'undan fazlası indekslenemez — "
                           "izolasyon fazla agresif")

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
