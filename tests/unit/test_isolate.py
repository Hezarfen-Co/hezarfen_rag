"""Faz 0.4 birim testleri — sızıntı izolasyonu (sentetik, deterministik)."""
import unittest

from src.ingest.pdf_parse import Block, Page, HEADING, HEADER, PARAGRAPH
from src.ingest.isolate import (page_exclusion_reason, block_is_assessment,
                                block_is_question_options)


def _page(*blocks):
    return Page(number=1, width=400, height=560, blocks=list(blocks))


def _b(text, kind=PARAGRAPH):
    return Block(page=1, bbox=(0, 0, 100, 20), text=text, block_no=0, kind=kind)


class QuestionOptionTests(unittest.TestCase):
    def test_five_options_is_question(self):
        self.assertTrue(block_is_question_options(
            "Aşağıdakilerden hangisi? A) x B) y C) z D) w E) q"))

    def test_single_option_not_question(self):
        self.assertFalse(block_is_question_options("A vitamini A) grubundadır"))

    def test_letter_inside_word_not_counted(self):
        # 'DNA)' gibi kelime-içi değil; gerçek şık işaretleri sayılır
        self.assertFalse(block_is_question_options("mRNA) ve tRNA) yapıları"))

    def test_normal_paragraph_not_question(self):
        self.assertFalse(block_is_question_options("DNA çift sarmal bir moleküldür."))


class AssessmentTests(unittest.TestCase):
    def test_assessment_markers(self):
        self.assertTrue(block_is_assessment("Ünite Değerlendirme Soruları"))
        self.assertTrue(block_is_assessment("ÖLÇME VE DEĞERLENDİRME"))
        self.assertTrue(block_is_assessment("Öz Değerlendirme"))

    def test_normal_not_assessment(self):
        self.assertFalse(block_is_assessment("Fotosentez kloroplastta gerçekleşir."))


class PageExclusionTests(unittest.TestCase):
    def test_kaynakca_heading_excluded(self):
        self.assertEqual(page_exclusion_reason(_page(_b("KAYNAKÇA", HEADER))), "kaynakca")

    def test_icindekiler_excluded(self):
        self.assertEqual(page_exclusion_reason(_page(_b("İÇİNDEKİLER", HEADING))), "icindekiler")

    def test_kitap_tanitimi_tr_lower(self):
        # TR harf tuzağı: "KİTAP TANITIMI" doğru eşleşmeli
        self.assertEqual(page_exclusion_reason(_page(_b("KİTAP TANITIMI", HEADER))), "kitap_tanitimi")

    def test_cevap_anahtari_in_body_not_excluded(self):
        # gövdede 'cevap anahtarı' geçmesi (içindekiler) sayfayı HARİÇ ETMEZ
        pg = _page(_b("2. Ünite", HEADING),
                   _b("Soruların cevap anahtarı karekodda verilmiştir.", PARAGRAPH))
        self.assertIsNone(page_exclusion_reason(pg))

    def test_teaching_page_not_excluded(self):
        pg = _page(_b("1.2.2. Genetik Mühendisliği", HEADING),
                   _b("Genetik mühendisliği DNA'yı değiştirir.", PARAGRAPH))
        self.assertIsNone(page_exclusion_reason(pg))


if __name__ == "__main__":
    unittest.main()
