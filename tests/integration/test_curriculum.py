"""Faz 0.7 integration testi — gerçek kazanimlar.json'dan curriculum graph."""
import os
import unittest

import corpus

from src.curriculum import load, load_from_vault

BIO = os.path.join(os.path.dirname(corpus.book_path() or ""), "kazanimlar.json")
DATA = "data"


@unittest.skipUnless(os.path.exists(BIO), f"veri yok: {BIO}")
class CurriculumGraphTests(unittest.TestCase):
    """Kazanım grafı — SAYILAR korpusa özgüdür, YAPI değişmezdir.

    Eski hâli 12-bio'ya çakılıydı (29 kazanım, 4 ünite, kod `12.1.1.1`) ve o
    kitap depoda olmadığı için test **hiç koşmuyordu**. Sabitler yıllardır
    doğrulanmamıştı. Artık her korpusta geçerli değişmezler sınanıyor."""

    @classmethod
    def setUpClass(cls):
        yol, sinif, ders = corpus.find_book()
        cls.sinif, cls.ders = sinif, ders
        cls.g = load(BIO, sinif=sinif, ders=ders)

    def test_graph_is_not_empty(self):
        self.assertGreater(len(self.g), 5)

    def test_units_are_grouped(self):
        units = self.g.units()
        self.assertTrue(units)
        for uid, ad in units:
            self.assertIsInstance(ad, str)
            self.assertTrue(ad.strip(), "ünite adı boş")

    def test_every_objective_carries_its_scope(self):
        for k in self.g.kazanimlar:
            self.assertEqual(k.sinif, self.sinif)
            self.assertEqual(k.ders, self.ders)

    def test_codes_are_unique_and_start_with_the_grade(self):
        kodlar = [k.kod for k in self.g.kazanimlar if k.kod]
        self.assertEqual(len(kodlar), len(set(kodlar)), "kazanım kodu tekrar ediyor")
        for kod in kodlar:
            self.assertTrue(kod.startswith(self.sinif + "."),
                            f"{kod} sınıf {self.sinif} ile başlamıyor")

    def test_lookup_by_code_round_trips(self):
        kodlu = [k for k in self.g.kazanimlar if k.kod]
        if not kodlu:
            self.skipTest("kodlu kazanım yok")
        ilk = kodlu[0]
        self.assertIs(self.g.by_kod(ilk.kod), ilk)

    def test_unknown_code_returns_none(self):
        self.assertIsNone(self.g.by_kod("99.9.9.9"))


@unittest.skipUnless(os.path.isdir(DATA), "veri yok")
class CurriculumVaultTests(unittest.TestCase):
    def test_vault_merges_many_subjects(self):
        g = load_from_vault(DATA)
        # lise'de kazanimlar.json'lu birçok ders var → çok sayıda kazanım + ders
        self.assertGreater(len(g), 100)
        self.assertGreater(len(g.subjects()), 5)


if __name__ == "__main__":
    unittest.main()
