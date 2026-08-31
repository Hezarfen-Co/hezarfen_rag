"""Faz 0.7 integration testi — gerçek kazanimlar.json'dan curriculum graph."""
import os
import unittest

from src.curriculum import load, load_from_vault

BIO = os.path.join("data", "lise", "12", "biyoloji", "kazanimlar.json")
DATA = "data"


@unittest.skipUnless(os.path.exists(BIO), f"veri yok: {BIO}")
class Curriculum12BioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = load(BIO, sinif="12", ders="biyoloji")

    def test_kazanim_count(self):
        self.assertEqual(len(self.g), 29)

    def test_units(self):
        units = self.g.units()
        self.assertEqual(len(units), 4)
        self.assertIn((32, "Genden Proteine"), units)

    def test_by_kod_dna(self):
        k = self.g.by_kod("12.1.1.1")
        self.assertIsNotNone(k)
        self.assertIn("keşif", k.metin.lower())
        self.assertEqual(k.sinif, "12")


@unittest.skipUnless(os.path.isdir(DATA), "veri yok")
class CurriculumVaultTests(unittest.TestCase):
    def test_vault_merges_many_subjects(self):
        g = load_from_vault(DATA)
        # lise'de kazanimlar.json'lu birçok ders var → çok sayıda kazanım + ders
        self.assertGreater(len(g), 100)
        self.assertGreater(len(g.subjects()), 5)


if __name__ == "__main__":
    unittest.main()
