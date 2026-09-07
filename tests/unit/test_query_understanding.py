"""#14 Sorgu anlama — intent + NER (deterministik, model gerektirmez)."""
import unittest

from src.understand import Intent, analyze, classify_intent, extract_entities


class IntentTests(unittest.TestCase):
    def test_intents(self):
        cases = {
            "DNA nedir?": Intent.TANIM,
            "Fotosentez nasıl gerçekleşir?": Intent.ACIKLAMA,
            "DNA ile RNA arasındaki fark nedir?": Intent.KARSILASTIRMA,   # tanım'dan önce
            "Mitokondri neden enerji üretir?": Intent.NEDEN_SONUC,
            "Kaç gram tuz gerekir?": Intent.HESAPLAMA,
            "Canlıların ortak özellikleri nelerdir?": Intent.LISTE,
            "Bu konuyu özetle": Intent.OZET,
            "Merhaba, nasılsın?": Intent.SOHBET,
            "": Intent.DIGER,
        }
        for q, exp in cases.items():
            self.assertEqual(classify_intent(q), exp, q)

    def test_out_of_scope_and_summary_flags(self):
        self.assertTrue(analyze("Selam!").is_out_of_scope)
        self.assertTrue(analyze("Bunu özetler misin").wants_summary)
        self.assertFalse(analyze("DNA nedir").is_out_of_scope)


class NerTests(unittest.TestCase):
    def test_acronyms_and_proper_and_formula(self):
        self.assertIn("DNA", extract_entities("DNA'nın yapısı nedir?"))
        self.assertIn("Watson-Crick", extract_entities("Watson-Crick modelini açıkla"))
        self.assertIn("H2O", extract_entities("H2O molekülü polar mıdır?"))

    def test_quoted_term(self):
        self.assertIn("hücre zarı", extract_entities('"hücre zarı" nedir?'))

    def test_no_entities_empty(self):
        self.assertEqual(extract_entities(""), [])

    def test_dedup_and_order(self):
        ents = extract_entities("DNA ve DNA tekrar; ATP")
        self.assertEqual(ents, ["DNA", "ATP"])   # tekrarsız, sıra korunur


if __name__ == "__main__":
    unittest.main()
