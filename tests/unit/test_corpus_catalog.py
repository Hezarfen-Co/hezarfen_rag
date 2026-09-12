"""EBA kataloğu — SPA bundle'ından materyal ve kazanım envanteri.

NEDEN VAR: `eba_dl/` altındaki eski indiriciler sunucu-render HTML ayrıştırıyordu.
Site SPA'ya dönüştü ve `konu-ozetleri?...` artık **924 baytlık boş kabuk**
döndürüyor; eski akış "0 items" deyip sessizce hiçbir şey getirmiyordu (ölçüldü).
Listeler JS bundle'ının içinde.

Testler ağa ÇIKMAZ: `parse_bundle` saf bir metin ayrıştırıcısıdır.
"""
import unittest

from src.corpus.eba_catalog import (Material, fold, grade_and_curriculum,
                                    objectives, parse_bundle, subject_slug,
                                    summary)

# Gerçek bundle'dan alınmış biçim (kısaltılmış)
_JS = '''
var a=[{grade:"11",lesson:"Biyoloji",unit:"\\u0130nsan Fizyolojisi",
outcome:"11.1.1.1.- Sinir sisteminin yap\\u0131, g\\u00f6rev ve i\\u015fleyi\\u015fini a\\u00e7\\u0131klar.",
title:"N\\u00d6RONLARI TANIYALIM",pdfUrl:"https://ogmmateryal.eba.gov.tr/panel/upload/a.pdf"},
{grade:"10. S\\u0131n\\u0131f (2017-23 M\\u00fcfredat\\u0131)",lesson:"Fizik",unit:"Bas\\u0131n\\u00e7",
outcome:"10.2.1.1.- Bas\\u0131nc\\u0131 a\\u00e7\\u0131klar.",title:"BASIN\\u00c7",
pdfUrl:"https://ogmmateryal.eba.gov.tr/panel/upload/b.pdf"},
{grade:"Se\\u00e7meli",lesson:"Astronomi",title:"X",pdfUrl:"https://ogmmateryal.eba.gov.tr/c.pdf"},
{lesson:"Tarih",title:"Tarih - Test 4",pdfUrl:"https://ogmmateryal.eba.gov.tr/panel/upload/d.pdf"},
{title:"pdf yok"}];
'''


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.mats = parse_bundle(_JS)

    def test_only_objects_with_a_pdf_are_taken(self):
        self.assertEqual(len(self.mats), 4)
        self.assertTrue(all(m.pdf_url.startswith("http") for m in self.mats))

    def test_turkish_text_is_decoded_correctly(self):
        """`bytes.decode("unicode_escape")` KULLANILMAZ: latin-1 varsayar ve
        UTF-8 Türkçe karakterleri bozar ("Sınıf" → "SÄ±nÄ±f"). İlk denemede
        tam olarak bu oldu; JSON çözücüye geçildi."""
        m = self.mats[0]
        self.assertEqual(m.unite, "İnsan Fizyolojisi")
        self.assertIn("işleyişini", m.kazanim)
        self.assertEqual(m.baslik, "NÖRONLARI TANIYALIM")

    def test_objective_code_is_extracted(self):
        self.assertEqual(self.mats[0].kazanim_kodu, "11.1.1.1")

    def test_subject_slug_maps_to_corpus_folders(self):
        self.assertEqual(self.mats[0].ders, "biyoloji")
        self.assertEqual(self.mats[1].ders, "fizik")

    def test_unknown_subject_is_none_not_a_guess(self):
        astro = next(m for m in self.mats if m.ders_adi == "Astronomi")
        self.assertIsNone(astro.ders)

    def test_missing_grade_yields_no_grade(self):
        tarih = next(m for m in self.mats if m.ders_adi == "Tarih")
        self.assertIsNone(tarih.sinif)


class CurriculumLabelTests(unittest.TestCase):
    """Katalog iki müfredat etiketi kullanıyor; ayrımı VERİDEN okuyoruz."""

    def test_plain_grade_is_current(self):
        self.assertEqual(grade_and_curriculum("11"), ("11", "guncel"))

    def test_2017_23_label_is_detected(self):
        self.assertEqual(grade_and_curriculum("10. Sınıf (2017-23 Müfredatı)"),
                         ("10", "2017-23"))

    def test_non_grade_labels_are_rejected(self):
        for etiket in ("Seçmeli", "Hepsi", "", None):
            with self.subTest(etiket):
                self.assertEqual(grade_and_curriculum(etiket)[0], None)

    def test_out_of_band_grades_are_rejected(self):
        self.assertIsNone(grade_and_curriculum("4")[0])
        self.assertIsNone(grade_and_curriculum("13")[0])


class ObjectivesTests(unittest.TestCase):
    def test_objectives_are_grouped_by_grade_and_subject(self):
        o = objectives(parse_bundle(_JS), curriculum="hepsi")
        self.assertIn(("11", "biyoloji"), o)
        self.assertIn(("10", "fizik"), o)

    def test_curriculum_filter_works(self):
        mats = parse_bundle(_JS)
        self.assertNotIn(("10", "fizik"), objectives(mats, curriculum="guncel"))
        self.assertNotIn(("11", "biyoloji"), objectives(mats, curriculum="2017-23"))

    def test_objective_text_drops_the_code_prefix(self):
        o = objectives(parse_bundle(_JS), curriculum="guncel")
        kayit = o[("11", "biyoloji")][0]
        self.assertEqual(kayit["kod"], "11.1.1.1")
        self.assertFalse(kayit["metin"].startswith("11.1.1.1"))
        self.assertTrue(kayit["metin"].startswith("Sinir sistemi"))

    def test_material_without_a_code_is_skipped(self):
        o = objectives(parse_bundle(_JS), curriculum="hepsi")
        self.assertNotIn(("9", "tarih"), o)


class FoldTests(unittest.TestCase):
    def test_turkish_case_folding(self):
        self.assertEqual(fold("İNGİLİZCE"), fold("ingilizce"))
        self.assertEqual(fold("Coğrafya"), fold("COĞRAFYA"))

    def test_subject_slug_handles_parenthetical_variants(self):
        self.assertEqual(subject_slug("İngilizce (Beceri Temelli)"), "ingilizce")


class SummaryTests(unittest.TestCase):
    def test_summary_counts(self):
        o = summary(parse_bundle(_JS))
        self.assertEqual(o["toplam"], 4)
        self.assertEqual(o["kazanimli"], 2)
        # "Seçmeli" ve sınıfsız kayıt "bilinmiyor" olur — güncel SAYILMAZ.
        # (İlk yazımda 3 beklemiştim; sayım kuralını yanlış varsaymışım.)
        self.assertEqual(o["guncel_mufredat"], 1)
        self.assertEqual(o["eski_mufredat"], 1)
        self.assertEqual(o["sinifi_cozulen"], 2)


if __name__ == "__main__":
    unittest.main()
