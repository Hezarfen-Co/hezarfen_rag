"""eval/runner saf-fonksiyon testleri (AUDIT EXP-007 #29 — runner 0-test'ti).
Ağ/model gerektirmez; yalnız aggregate/seçim/skor mantığı."""
import unittest

from src.eval import runner as R


def _item(id, beh="cevapla", critical=False, unite=None,
          recall20=None, citR=None, judge=None, guard_passed=None, fail_closed=None,
          error=None):
    d = {
        "id": id, "kategori": "orta", "unite": unite, "beklenen_davranis": beh,
        "critical": critical,
        "retrieval": {"recall_at_20": recall20, "recall_at_10": recall20},
        "citation": {"recall": citR, "precision": None},
        "guardrail": {"passed": guard_passed, "fail_closed": fail_closed,
                      "abstained": False, "reason": ""},
        "judge": judge,
    }
    if error:
        d["error"] = error
    return d


class SelectJudgeIdsTests(unittest.TestCase):
    def test_critical_and_unite_backfill(self):
        items = [
            {"id": "a", "beklenen_davranis": "cevapla", "critical": True, "unite": "U1"},
            {"id": "b", "beklenen_davranis": "cevapla", "critical": False, "unite": "U1"},
            {"id": "c", "beklenen_davranis": "cevapla", "critical": False, "unite": "U2"},
            {"id": "d", "beklenen_davranis": "red", "critical": True, "unite": "U3"},   # cevapla değil → yok
        ]
        ids = R._select_judge_ids(items)
        self.assertIn("a", ids)        # critical cevapla
        self.assertIn("c", ids)        # U2 temsil edilmemişti → backfill
        self.assertNotIn("b", ids)     # U1 zaten 'a' ile temsil
        self.assertNotIn("d", ids)     # red → hakem yok

    def test_missing_unite_no_crash(self):
        items = [{"id": "x", "beklenen_davranis": "cevapla", "critical": True}]  # unite yok
        self.assertEqual(R._select_judge_ids(items), {"x"})


class AggregateTests(unittest.TestCase):
    def test_none_drop_and_per_metric_n(self):
        items = [
            _item("a", recall20=1.0, citR=0.8,
                  judge={"faithfulness": 0.9, "answer_relevancy": 1.0, "answer_correctness": 0.8}),
            _item("b", recall20=0.5, citR=None,
                  judge={"faithfulness": None, "answer_relevancy": 1.0,   # faith None (hakem hatası)
                         "answer_correctness": 0.6, "errors": ["timeout"]}),
        ]
        agg = R._aggregate(items)
        self.assertAlmostEqual(agg["retrieval"]["recall_at_20"], 0.75)
        self.assertEqual(agg["judge"]["n_judged"], 2)
        self.assertEqual(agg["judge"]["faithfulness_n"], 1)     # yalnız 'a' katkı verdi
        self.assertEqual(agg["judge"]["answer_relevancy_n"], 2)
        self.assertEqual(agg["judge"]["n_errors"], 1)
        self.assertAlmostEqual(agg["judge"]["faithfulness"], 0.9)   # None düştü → tek değer

    def test_empty_subset(self):
        agg = R._aggregate([])
        self.assertEqual(agg["n"], 0)
        self.assertIsNone(agg["guardrail_pass_rate"])


class WeaknessScoreTests(unittest.TestCase):
    def test_guardrail_fail_is_zero(self):
        self.assertEqual(R._weakness_score(_item("a", guard_passed=False)), 0.0)
    def test_error_item_is_zero(self):
        self.assertEqual(R._weakness_score(R._failed_item({"id": "e"}, ValueError("x"))), 0.0)
    def test_normal_average(self):
        it = _item("a", recall20=1.0, citR=0.6)
        self.assertAlmostEqual(R._weakness_score(it), 0.8)   # (1.0+0.6)/2


class FailedItemTests(unittest.TestCase):
    def test_failed_item_aggregate_compatible(self):
        fi = R._failed_item({"id": "z", "kategori": "orta", "soru": "s"}, KeyError("beklenen_davranis"))
        # aggregate ile uyumlu (çökmeden işlenmeli)
        agg = R._aggregate([fi])
        self.assertEqual(agg["n"], 1)
        self.assertEqual(agg["n_errors"], 1)
        self.assertIn("eval_error", fi["generation"]["reason"])


if __name__ == "__main__":
    unittest.main()
