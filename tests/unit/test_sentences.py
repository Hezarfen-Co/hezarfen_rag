"""#56 (EXP-010/ACC-07) — Türkçe cümle bölme + atıf bütünlüğü ölçümü.

Bölücü ayrı test edilir çünkü YANLIŞ BÖLME ÖLÇÜMÜ İKİ YÖNDE DE BOZAR: fazla
bölme atıfsız cümle oranını şişirir (yapay kapı ihlali), az bölme gizler
(yapay geçiş). Kapı A-03 doğrudan bu sayıdan hesaplanıyor.
"""
import unittest

from src.generate.sentences import (citation_coverage, drop_uncited, is_bullet,
                                    is_cited, split_sentences)


class SplitTests(unittest.TestCase):
    def test_basic_three_sentences(self):
        t = "DNA çift sarmaldır [1]. Ribozom protein üretir. Mitoz bölünmedir."
        self.assertEqual(len(split_sentences(t)), 3)

    def test_citation_stays_with_its_sentence(self):
        c = split_sentences("A olur [1]. B olur [2].")
        self.assertTrue(all(is_cited(x) for x in c))

    def test_abbreviations_do_not_split(self):
        for t in ("Bitkiler vb. canlılar fotosentez yapar [1].",
                  "Örn. glikoz taşınır [1].",
                  "Bkz. s. 12 [1].",
                  "Değer yak. 10 gramdır [1].",
                  "Dr. Ahmet açıkladı [1]."):
            with self.subTest(t):
                self.assertEqual(len(split_sentences(t)), 1, t)

    def test_initialisms_do_not_split(self):
        """İLK SÜRÜMDE YOKTU: "M.Ö. 300 yılında yaşadı [1]." İKİYE bölünüyor
        ("M.Ö." + "300 yılında...") ve atıfsız cümle oranını yapay olarak
        şişiriyordu. Koşarak görüldü."""
        for t in ("M.Ö. 300 yılında yaşadı [1].",
                  "T.C. Anayasası kabul edildi [1].",
                  "A.B.D. ve Rusya anlaştı [1]."):
            with self.subTest(t):
                self.assertEqual(len(split_sentences(t)), 1, t)

    def test_decimals_and_codes_do_not_split(self):
        for t in ("Değeri 3.14 olarak alınır [1].",
                  "10.1.1.2 Mitozu açıklar [1].",
                  "Oran 0.5 ile 1.5 arasındadır [1]."):
            with self.subTest(t):
                self.assertEqual(len(split_sentences(t)), 1, t)

    def test_bullets_are_separate_claims(self):
        """Madde listesindeki her kalem bağımsız bir iddiadır ve ayrı dayanak
        ister — tek bir atıf bütün listeyi kapsamış sayılmaz."""
        t = "- Üreticiler ototroftur [1]\n- Tüketiciler heterotroftur\n- Ayrıştırıcılar [2]"
        c = split_sentences(t)
        self.assertEqual(len(c), 3)
        self.assertTrue(is_bullet(c[0]))
        self.assertFalse(is_cited(c[1]))

    def test_question_and_exclamation_split(self):
        self.assertEqual(len(split_sentences("Bu nedir? Şudur [1]. Harika!")), 3)

    def test_empty_and_whitespace(self):
        for t in ("", "   ", "\n\n"):
            self.assertEqual(split_sentences(t), [])

    def test_no_terminal_punctuation_is_still_a_sentence(self):
        self.assertEqual(len(split_sentences("Atıfsız tek satır")), 1)

    def test_multiple_blank_lines_do_not_create_empty_sentences(self):
        c = split_sentences("A [1].\n\n\nB [2].")
        self.assertEqual(len(c), 2)


class CoverageTests(unittest.TestCase):
    def test_audit_scenario_is_measured(self):
        """Denetimin kanıtı: 5 cümlenin 4'ü atıfsız. Eskiden bu cevap
        `abstained=False, reason=''` ile temiz sayılıyordu."""
        t = ("Mitokondri enerji üretir [1]. Bir glikozdan 47 ATP üretilir. "
             "Ribozom nükleusta bulunur. İnsanda 48 kromozom vardır. "
             "Bu yüzden hücre bölünür.")
        k = citation_coverage(t)
        self.assertEqual(k["n_sentences"], 5)
        self.assertEqual(k["n_cited_sentences"], 1)
        self.assertEqual(k["uncited_ratio"], 0.8)
        self.assertEqual(len(k["uncited_sentences"]), 4)

    def test_fully_cited_answer_has_zero_ratio(self):
        k = citation_coverage("A olur [1]. B olur [2].")
        self.assertEqual(k["uncited_ratio"], 0.0)

    def test_empty_text_does_not_divide_by_zero(self):
        self.assertEqual(citation_coverage("")["uncited_ratio"], 0.0)


class DropTests(unittest.TestCase):
    def test_uncited_sentences_are_removed(self):
        metin, atilan = drop_uncited("A olur [1]. B olur. C olur [2].")
        self.assertIn("[1]", metin)
        self.assertIn("[2]", metin)
        self.assertNotIn("B olur", metin)
        self.assertEqual(atilan, ["B olur."])

    def test_line_structure_is_preserved(self):
        metin, _ = drop_uncited("- A [1]\n- B\n- C [2]")
        self.assertEqual(metin.count("\n"), 1)

    def test_everything_uncited_yields_empty(self):
        metin, atilan = drop_uncited("A olur. B olur.")
        self.assertEqual(metin, "")
        self.assertEqual(len(atilan), 2)


if __name__ == "__main__":
    unittest.main()
