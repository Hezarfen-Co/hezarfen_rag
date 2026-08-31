"""Faz 0.6 birim testleri — TR normalizasyon (edge case, gerçek PDF quirk'leri)."""
import unittest

from src.text import (tr_lower, tr_upper, strip_invisibles,
                      join_hyphenation, normalize, fold_for_match)


class TrCaseTests(unittest.TestCase):
    def test_lower_dotted_I(self):
        self.assertEqual(tr_lower("KİTAP"), "kitap")          # combining-dot tuzağı
        self.assertEqual(tr_lower("İSTANBUL"), "istanbul")

    def test_lower_dotless_I(self):
        self.assertEqual(tr_lower("IŞIK"), "ışık")
        self.assertEqual(tr_lower("ISI"), "ısı")

    def test_upper(self):
        self.assertEqual(tr_upper("iğne"), "İĞNE")
        self.assertEqual(tr_upper("ışık"), "IŞIK")


class InvisibleTests(unittest.TestCase):
    def test_strip_bom_zero_width(self):
        self.assertEqual(strip_invisibles("﻿gen aktarımı"), "gen aktarımı")
        self.assertEqual(strip_invisibles("a​b"), "ab")


class HyphenationTests(unittest.TestCase):
    def test_soft_hyphen_join(self):
        # gerçek quirk: "mü\xadhendisliği"
        self.assertEqual(join_hyphenation("mü\xadhendisliği"), "mühendisliği")

    def test_soft_hyphen_with_newline(self):
        self.assertEqual(join_hyphenation("çalış\xad\nmaları"), "çalışmaları")

    def test_linebreak_hyphen_join(self):
        self.assertEqual(join_hyphenation("düzen-\nleme"), "düzenleme")

    def test_midline_hyphen_preserved(self):
        # satır ORTASINDAKİ tire (bileşik) korunur
        self.assertEqual(join_hyphenation("neden-sonuç ilişkisi"), "neden-sonuç ilişkisi")


class NormalizeTests(unittest.TestCase):
    def test_full_pipeline(self):
        raw = "﻿Genetik  mü\xadhendisliği   DNA'yı\n\n\n\ndeğiştirir."
        out = normalize(raw)
        self.assertIn("mühendisliği", out)
        self.assertNotIn("﻿", out)
        self.assertNotIn("\xad", out)
        self.assertNotIn("   ", out)           # boşluk sıkışmış
        self.assertNotIn("\n\n\n", out)        # fazla yeni-satır sıkışmış

    def test_preserves_scientific_symbols(self):
        # alt-indis / özel simge KORUNMALI
        for token in ("CO₂", "H₂O", "3ʹ", "5ʹ", "β-galaktozidaz"):
            self.assertIn(token, normalize(f"metin {token} devam"))

    def test_empty(self):
        self.assertEqual(normalize(""), "")


class FoldTests(unittest.TestCase):
    def test_fold_lowercases_keeps_accents(self):
        # aksan korunur (biyolojik terim), harf-durumu eşitlenir
        self.assertEqual(fold_for_match("DNA Polimeraz"), "dna polimeraz")
        self.assertEqual(fold_for_match("Çekirdek"), "çekirdek")


if __name__ == "__main__":
    unittest.main()
