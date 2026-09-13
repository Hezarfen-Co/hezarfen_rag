"""Golden set ÜRETİCİSİNİN kendi kusurları (#65-#71).

Buradaki her test, ölçümde YANLIŞ SONUÇ ÜRETMİŞ gerçek bir kusuru kayda
geçirir. Bozuk bir ölçüm aracı bozuk bir üründen daha tehlikelidir: ürün
doğru davranırken "başarısız" raporu verir ve yanlış yeri düzeltmeye
çalışırsın.

ÖLÇÜLEN: `global` senaryosu recall@5 = **0,034**. Üç ayrı üretici kusuru
vardı; düzeltildikten sonra aynı üründe **0,659** ölçüldü. Ürün kodunda tek
satır değişmedi.
"""
import unittest

from src.eval.golden_build import _is_topic_heading, _clean_heading


class CleanHeadingTests(unittest.TestCase):
    """PDF'in başlık katmanı ham hâliyle soruya konamaz."""

    def test_repeated_lines_are_collapsed(self):
        # PyMuPDF gölgeli başlıkları iki kez döndürüyor.
        self.assertEqual(_clean_heading("10. Sınıf\n10. Sınıf"), "10. Sınıf")

    def test_repeated_words_are_collapsed(self):
        self.assertEqual(_clean_heading("1.\n1.\nTEMA\nTEMA"), "1. TEMA")

    def test_newline_never_survives_in_a_heading(self):
        # "SEMBOLLERİN\nAÇIKLAMASI" soruya gömülünce iki satıra bölünüyordu.
        self.assertEqual(_clean_heading("SEMBOLLERİN\nAÇIKLAMASI"),
                         "SEMBOLLERİN AÇIKLAMASI")

    def test_empty_input_does_not_crash(self):
        for x in ("", None, "   ", "\n\n"):
            self.assertEqual(_clean_heading(x), "")


class IsTopicHeadingTests(unittest.TestCase):
    """Başlık katmanında konu adı OLMAYAN şeyler de var."""

    def test_a_real_topic_is_accepted(self):
        for ad in ("Krebs (Sitrik Asit) Döngüsü", "Azot Döngüsü",
                   "Mide ve Bağırsak Adaptasyonları",
                   "IŞIK ENERJİSİ KULLANILARAK BESİN SENTEZİ (FOTOSENTEZ)"):
            with self.subTest(ad=ad):
                self.assertTrue(_is_topic_heading(ad))

    def test_chemical_equation_is_rejected(self):
        # "6CO2 + 12H2O Işık C6H12O6 + 6O2 + 6H2O konusunu anlatır mısın?"
        # diye bir öğrenci sorusu yoktur.
        for ad in ("6CO2 + 12H2O Işık C6H12O6 + 6O2 + 6H2O",
                   "Glikoz 2 Laktik asit + 2 ATP",
                   "C6H12O6 + 6O2 → 6CO2 + 6H2O"):
            with self.subTest(ad=ad):
                self.assertFalse(_is_topic_heading(ad))

    def test_figure_label_is_rejected(self):
        # Şekil içindeki harf dizileri de "heading" olarak geliyor.
        self.assertFalse(_is_topic_heading("P P P Pi P P"))

    def test_a_sentence_is_not_a_heading(self):
        self.assertFalse(_is_topic_heading(
            "Suyun fotolizi ile oluşan hidrojenler NADP+ tarafından tutulur."))

    def test_a_question_is_rejected(self):
        self.assertFalse(_is_topic_heading("Bitkilerin kütlesi nasıl artar? B"))


class GlobalItemTests(unittest.TestCase):
    """Üretilmiş setin `global` item'ları için değişmezler.

    Bunlar dosyanın kendisini denetler: üretici bozulursa set bozulur ve
    ölçüm sessizce yanlışa kayar.
    """

    @classmethod
    def setUpClass(cls):
        import json
        import os
        path = os.path.join("tests", "golden", "golden_10biy_v2.json")
        if not os.path.isfile(path):
            raise unittest.SkipTest("golden set uretilmemis")
        data = json.load(open(path, encoding="utf-8"))
        cls.global_items = [i for i in data["items"] if i["senaryo"] == "global"]

    def test_the_set_is_not_empty(self):
        self.assertGreaterEqual(len(self.global_items), 10)

    def test_questions_are_single_line(self):
        for i in self.global_items:
            self.assertNotIn("\n", i["soru"], i["id"])

    def test_no_page_range_questions(self):
        """"40-52. sayfaları özetle" retrieval sorusu değil, `/rag/summarize`
        kapsam girdisidir. Ölçümde recall@5 = 0,034 çıkmasının nedeniydi."""
        import re
        for i in self.global_items:
            self.assertIsNone(re.search(r"\d+\s*-\s*\d+\.\s*sayfa", i["soru"]),
                              i["soru"])

    def test_gold_evidence_is_real(self):
        for i in self.global_items:
            self.assertGreaterEqual(len(i["gold_kaynak_spanlar"]), 3, i["id"])
            self.assertTrue(i["gold_sayfalar"], i["id"])
            self.assertTrue(i["gold_cevap"].strip(), i["id"])

    def test_items_span_the_whole_book(self):
        """Adayları baştan kesmek 22 item'ın hepsini ilk temadan alıyordu;
        `global` ölçümü kitabın yalnız üçte birini görüyordu."""
        pages = [i["gold_sayfalar"][0] for i in self.global_items]
        self.assertGreater(max(pages) - min(pages), 80,
                           "global item'lar kitabin tek bolgesinde toplanmis")


class MultiTurnFieldTests(unittest.TestCase):
    """Alan adı uyuşmazlığı ölçümü sıfırlamıştı."""

    @classmethod
    def setUpClass(cls):
        import json
        import os
        path = os.path.join("tests", "golden", "golden_10biy_v2.json")
        if not os.path.isfile(path):
            raise unittest.SkipTest("golden set uretilmemis")
        data = json.load(open(path, encoding="utf-8"))
        cls.items = [i for i in data["items"] if i["senaryo"] == "multi_turn"]

    def test_history_field_matches_the_runner(self):
        # Üretici `gecmis`, runner `konusma_gecmisi` okuyordu: geçmiş hiç
        # ulaşmıyordu ve multi_turn recall@5 = 0,000 çıkıyordu.
        for i in self.items:
            self.assertTrue(i.get("konusma_gecmisi"), i["id"])


if __name__ == "__main__":
    unittest.main()
