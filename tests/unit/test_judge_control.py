"""#72 / #M3-9 (EVAL-06) — hakem negatif kontrol koşumunun KENDİ testleri.

Bu dosya hakemi değil, HAKEMİ ÖLÇEN ARACI sınar. Bozuk bir ölçüm aracı
bozuk bir üründen daha tehlikelidir: ürün doğruyken "başarısız" der.

En kritik test: her vakaya AYNI puanı veren bir hakem bu koşumdan
GEÇEMEMELİ. Yalnız negatif kontrol ölçen bir tasarımda "her şeye 0,1 veren"
hakem tam puan alırdı — bu yüzden pozitif kontrol zorunludur.
"""
import unittest

from src.eval.judge_control import (CORRUPTIONS, ControlCase, build_controls,
                                    cohen_kappa, run_controls)


def _item(i, gold="Fotosentez kloroplastta gerceklesir ve isik enerjisi artar.",
          davranis="cevapla"):
    return {"id": f"g{i}", "soru": f"soru {i} nedir", "gold_cevap": gold,
            "beklenen_davranis": davranis, "senaryo": "direct"}


class _FixedJudge:
    """Her şeye aynı puanı veren hakem — ayırt etme gücü SIFIR."""

    def __init__(self, score=0.9):
        self.score = score
        self.seen = []

    def evaluate(self, *, question, answer_text, retrieved_contexts, gold_answer):
        self.seen.append(answer_text)
        return type("R", (), {"faithfulness": self.score,
                              "answer_relevancy": self.score,
                              "answer_correctness": self.score,
                              "errors": []})()


class _PerfectJudge:
    """İdeal hakem: gold cevabın aynısına 1,0 başka her şeye 0,0."""

    def evaluate(self, *, question, answer_text, retrieved_contexts, gold_answer):
        iyi = (answer_text or "").strip() == (gold_answer or "").strip()
        v = 1.0 if iyi else 0.0
        return type("R", (), {"faithfulness": v, "answer_relevancy": v,
                              "answer_correctness": v, "errors": []})()


class _BrokenJudge:
    def evaluate(self, **kw):
        raise RuntimeError("judge api down")


class BuildControlsTests(unittest.TestCase):
    def test_half_positive_half_negative(self):
        cs = build_controls([_item(i) for i in range(40)], n=20)
        self.assertEqual(len(cs), 20)
        self.assertEqual(sum(1 for c in cs if c.expected == "high"), 10)
        self.assertEqual(sum(1 for c in cs if c.expected == "low"), 10)

    def test_every_corruption_kind_is_represented(self):
        """İlk sürümde bozma türü `len(cases) % 5` ile seçiliyordu; pozitif
        vakalar sayacı ikişer kaydırdığı için beş türün yalnız ikisi
        üretiliyordu."""
        cs = build_controls([_item(i) for i in range(60)], n=20)
        turler = {c.kind for c in cs if c.expected == "low"}
        self.assertEqual(turler, set(CORRUPTIONS))

    def test_positive_case_is_the_gold_answer_verbatim(self):
        cs = build_controls([_item(1)], n=2)
        poz = [c for c in cs if c.expected == "high"][0]
        self.assertEqual(poz.answer_text, poz.gold_answer)

    def test_fabricated_case_keeps_the_gold_and_adds_a_lie(self):
        """Baştan sona saçma bir cevabı ayırmak kolaydır; gerçek sınav,
        çoğu doğru ama BİR cümlesi uydurma olan cevaptır."""
        cs = build_controls([_item(i) for i in range(60)], n=20)
        uyd = [c for c in cs if c.kind == "fabricated_fact"][0]
        self.assertIn(uyd.gold_answer, uyd.answer_text)
        self.assertGreater(len(uyd.answer_text), len(uyd.gold_answer))

    def test_abstain_items_are_excluded(self):
        """Çekimser kalınması beklenen item'da "cevabın kalitesi" diye bir
        şey yoktur."""
        items = [_item(i, davranis="cekimser") for i in range(20)]
        self.assertEqual(build_controls(items, n=10), [])

    def test_items_without_gold_are_excluded(self):
        self.assertEqual(build_controls([_item(i, gold="  ") for i in range(20)],
                                        n=10), [])

    def test_generation_is_deterministic(self):
        items = [_item(i) for i in range(40)]
        a = [(c.id, c.kind, c.answer_text) for c in build_controls(items, n=20)]
        b = [(c.id, c.kind, c.answer_text) for c in build_controls(items, n=20)]
        self.assertEqual(a, b)

    def test_negation_actually_flips_a_claim(self):
        cs = build_controls([_item(i) for i in range(60)], n=20)
        neg = [c for c in cs if c.kind == "negation"]
        self.assertTrue(neg)
        self.assertNotEqual(neg[0].answer_text, neg[0].gold_answer)


class RunControlsTests(unittest.TestCase):
    def setUp(self):
        self.cases = build_controls([_item(i) for i in range(60)], n=20)

    def test_a_perfect_judge_separates_fully(self):
        r = run_controls(_PerfectJudge(), self.cases)
        self.assertEqual(r.n, 20)
        self.assertEqual(r.errors, [])
        for m in ("faithfulness", "answer_relevancy", "answer_correctness"):
            self.assertAlmostEqual(r.discrimination[m], 1.0, places=6)

    def test_a_constant_judge_has_zero_discrimination(self):
        """ASIL TEST. Her şeye 0,9 veren hakem de, her şeye 0,1 veren hakem
        de ayırt etme gücü SIFIR gösterir. Yalnız negatif kontrol ölçen bir
        tasarımda ikincisi TAM PUAN alırdı."""
        for skor in (0.9, 0.5, 0.1):
            with self.subTest(skor=skor):
                r = run_controls(_FixedJudge(skor), self.cases)
                for m in ("faithfulness", "answer_relevancy"):
                    self.assertAlmostEqual(r.discrimination[m], 0.0, places=6)

    def test_positive_and_negative_are_reported_separately(self):
        r = run_controls(_PerfectJudge(), self.cases)
        self.assertEqual(r.positive["faithfulness"]["n"], 10)
        self.assertEqual(r.negative["faithfulness"]["n"], 10)
        self.assertAlmostEqual(r.positive["faithfulness"]["mean"], 1.0)
        self.assertAlmostEqual(r.negative["faithfulness"]["mean"], 0.0)

    def test_confidence_interval_is_reported(self):
        """Tek sayı karar için yetmez; 20 vakada ortalamanın belirsizliği
        büyüktür."""
        r = run_controls(_PerfectJudge(), self.cases)
        self.assertIsNotNone(r.positive["faithfulness"]["ci"])

    def test_judge_failure_is_recorded_not_swallowed(self):
        """pass-bias YASAK: hakem çöktüğünde koşum sessizce 'ayrım yok'
        dememeli, HATA raporlamalı."""
        r = run_controls(_BrokenJudge(), self.cases)
        self.assertEqual(len(r.errors), 20)
        self.assertIsNone(r.discrimination["faithfulness"])

    def test_by_kind_only_counts_the_targeted_metric(self):
        """Konu dışı bir cevap bağlama SADIK olabilir; faithfulness'ı
        `off_topic` kırılımına yazmak hakemi haksız yere suçlardı."""
        r = run_controls(_PerfectJudge(), self.cases)
        self.assertIn("answer_relevancy", r.by_kind["off_topic"])
        self.assertNotIn("faithfulness", r.by_kind["off_topic"])

    def test_report_is_json_serialisable(self):
        import json
        json.dumps(run_controls(_PerfectJudge(), self.cases).to_dict())

    def test_no_pass_fail_verdict_is_emitted(self):
        """Araç kendini geçmiş ilan ETMEZ; ölçüm döner, kararı insan verir."""
        r = run_controls(_PerfectJudge(), self.cases).to_dict()
        for yasak in ("passed", "gecti", "verdict", "ok"):
            self.assertNotIn(yasak, r)


class CohenKappaTests(unittest.TestCase):
    """#M3-9 TAM kapısı: insan etiketiyle κ ≥ 0,75. İnsan etiketi gelene
    kadar (#91) hesap hazır durur."""

    def test_perfect_agreement(self):
        self.assertEqual(cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]), 1.0)

    def test_chance_agreement_is_near_zero(self):
        a = [1, 0, 1, 0, 1, 0, 1, 0]
        b = [1, 1, 0, 0, 1, 1, 0, 0]
        self.assertLess(abs(cohen_kappa(a, b)), 0.1)

    def test_total_disagreement_is_negative(self):
        self.assertLess(cohen_kappa([1, 0, 1, 0], [0, 1, 0, 1]), 0)

    def test_single_class_is_undefined_not_perfect(self):
        """Herkes her şeye 'iyi' derse uyum şansa eşittir; 1,0 döndürmek
        'mükemmel uyum' yanılsaması yaratırdı."""
        self.assertIsNone(cohen_kappa([1, 1, 1, 1], [1, 1, 1, 1]))

    def test_mismatched_lengths(self):
        self.assertIsNone(cohen_kappa([1, 0], [1]))
        self.assertIsNone(cohen_kappa([], []))


if __name__ == "__main__":
    unittest.main()
