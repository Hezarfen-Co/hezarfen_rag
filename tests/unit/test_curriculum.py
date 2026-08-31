"""Faz 0.7 birim testleri — curriculum graph (sentetik, deterministik)."""
import unittest

from src.curriculum import Kazanim, CurriculumGraph, parse_kod


def _k(kid, kod, unite_id, unite, metin="x", sinif="12", ders="biyoloji"):
    return Kazanim(kazanim_id=kid, kod=kod, metin=metin, unite_id=unite_id,
                   unite=unite, sinif=sinif, ders=ders)


class ParseKodTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_kod("12.1.1.1"), (12, 1, 1, 1))
        self.assertEqual(parse_kod("8.3.2.4"), (8, 3, 2, 4))

    def test_invalid(self):
        self.assertIsNone(parse_kod("abc"))
        self.assertIsNone(parse_kod(""))
        self.assertIsNone(parse_kod("12.1"))


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.g = CurriculumGraph([
            _k(3522, "12.1.1.1", 32, "Genden Proteine", "Nükleik asit keşfi"),
            _k(3523, "12.1.1.2", 32, "Genden Proteine", "Nükleik asit çeşitleri"),
            _k(3540, "12.2.1.1", 33, "Enerji Dönüşümleri", "ATP"),
        ])

    def test_len_and_by_id(self):
        self.assertEqual(len(self.g), 3)
        self.assertEqual(self.g.by_id(3523).kod, "12.1.1.2")

    def test_by_kod(self):
        self.assertEqual(self.g.by_kod("12.1.1.1").metin, "Nükleik asit keşfi")
        self.assertIsNone(self.g.by_kod("99.9.9.9"))

    def test_units(self):
        self.assertEqual(self.g.units(), [(32, "Genden Proteine"), (33, "Enerji Dönüşümleri")])

    def test_kazanimlar_of_unit(self):
        self.assertEqual(len(self.g.kazanimlar_of(32)), 2)
        self.assertEqual(len(self.g.kazanimlar_of(33)), 1)

    def test_subjects(self):
        self.assertEqual(self.g.subjects(), [("12", "biyoloji")])


if __name__ == "__main__":
    unittest.main()
