"""Faz 0.3c integration testi — gerçek 12-bio'da tablo tespiti + filtre.
Hız için YALNIZ birkaç sayfa taranır (tüm kitap pdfplumber'da yavaş)."""
import os
import unittest

import corpus

from src.ingest.tables import extract_tables

BOOK = corpus.book_path()


@corpus.requires_book
class TableExtractionTests(unittest.TestCase):


    def test_a_real_table_is_found_somewhere_in_the_book(self):
        """Ders kitabında en az bir GERÇEK tablo bulunmalı.

        Eski hâli "sayfa 20'de DNA/RNA karşılaştırma tablosu" diyordu — 12-bio'ya
        özgü. O kitap depoda olmadığı için test **hiç koşmuyordu** ve iddia
        yıllardır doğrulanmamıştı. Değişmez: bir ders kitabında tablo VARDIR,
        çıkarıcı en az birini bulmalı ve bulduğu boş olmamalı."""
        bulunan = []
        for sayfa in range(15, 120, 12):          # kitabın içine yayılmış örnekleme
            for t in extract_tables(BOOK, pages=[sayfa]).get(sayfa, []):
                bulunan.append((sayfa, t))
            if bulunan:
                break
        self.assertTrue(bulunan, "örneklenen sayfaların hiçbirinde tablo yok")
        _, ilk = bulunan[0]
        hucreler = [h for satir in ilk.rows for h in satir if (h or "").strip()]
        self.assertGreaterEqual(len(hucreler), 4, "bulunan tablo fiilen boş")
        self.assertGreaterEqual(ilk.n_rows, 2)
        self.assertGreaterEqual(ilk.n_cols, 2)

    def test_decorative_boxes_stay_filtered(self):
        """Filtre zayıflarsa dekoratif kutular tablo sayılır ve atıf kirlenir."""
        for sayfa in (1, 2, 3):
            self.assertEqual(extract_tables(BOOK, pages=[sayfa]).get(sayfa, []), [],
                             f"sayfa {sayfa}: dekoratif kutu gerçek tablo sayıldı")
