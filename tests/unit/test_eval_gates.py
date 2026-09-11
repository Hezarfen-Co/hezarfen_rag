"""M0-9 (#41) — kapı-izleme matrisi testleri.

NEDEN (EXP-010/EVAL-15): `benchmark.md §3`'ün 26 kapısından yalnız ~5'i (o da
vekil metriklerle) ölçülüyordu ve hangisinin ölçüldüğü ELLE takip ediliyordu.
"Neyi ölçmüyoruz?" sorusu belgeye bakmadan cevaplanamıyordu.

Bu testler iki şeyi sabitler:
1. Ölçülmeyen kapı GİZLENMEZ — `ÖLÇÜLMEDİ` olarak listede kalır ve nedeni yazar.
2. CI olmadan hiçbir kapı `GEÇTİ` sayılamaz (pass-bias yasağı, #33).
"""
import unittest

from src.eval.gates import (GATES, by_dimension, evaluate_gates, render_matrix,
                            summary)


def _payload(**over):
    base = {
        "overall": {
            "n": 200, "n_guardrail_applicable": 67, "n_abstained": 45,
            "retrieval": {"recall_at_5": 0.90, "recall_at_10": 0.93,
                          "recall_at_20": 0.99, "mrr_value": 0.88,
                          "ndcg_at_10": 0.90,
                          "all_evidence_recall_at_20": 0.95},
            "citation": {"recall_page": 0.95, "precision_page": 0.90},
            "guardrail_pass_rate": 1.0, "fail_closed_rate": 1.0,
            "judge": {"n_judged": 40, "n_judge_selected": 40,
                      "faithfulness_penalized": 0.98},
        },
        "items": [],
    }
    base["overall"].update(over)
    return base


class GateTableTests(unittest.TestCase):
    def test_every_gate_has_id_name_and_note_or_path(self):
        for g in GATES:
            with self.subTest(g.gid):
                self.assertTrue(g.gid and g.ad)
                # ölçülmeyen kapı NEDENİNİ yazmak zorunda
                if g.path is None:
                    self.assertTrue(g.not_, f"{g.gid}: ölçülmüyor ama not yok")

    def test_gate_ids_unique(self):
        ids = [g.gid for g in GATES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_security_gates_have_equal_mvp_and_full_thresholds(self):
        """benchmark.md §8: güvenlik kapıları KADEMEYE GÖRE GEVŞETİLEMEZ."""
        for g in GATES:
            if g.gid.startswith("G-"):
                with self.subTest(g.gid):
                    self.assertEqual(g.mvp, g.tam)

    def test_full_thresholds_are_never_looser_than_mvp(self):
        for g in GATES:
            if g.mvp is None or g.tam is None:
                continue
            with self.subTest(g.gid):
                if g.higher_is_better:
                    self.assertGreaterEqual(g.tam, g.mvp)
                else:
                    self.assertLessEqual(g.tam, g.mvp)


class EvaluationTests(unittest.TestCase):
    def test_unmeasured_gates_are_listed_not_hidden(self):
        """Ölçen kodu olmayan kapı listeden DÜŞMEZ; durumu ÖLÇÜLMEDİ olur
        (ya da o kademede hiç yoksa ATLANDI) ve nedeni HER ZAMAN yazılır."""
        rows = evaluate_gates(_payload())
        unmeasured = [r for r in rows if not r["olculuyor"]]
        self.assertGreater(len(unmeasured), 0)
        for r in unmeasured:
            with self.subTest(r["gid"]):
                self.assertIn(r["durum"], ("ÖLÇÜLMEDİ", "ATLANDI"))
                self.assertTrue(r["not"], f"{r['gid']}: neden yazılmamış")
                self.assertNotEqual(r["durum"], "GEÇTİ")   # asla geçmiş sayılmaz

    def test_gate_passes_only_when_ci_lower_clears_threshold(self):
        rows = {r["gid"]: r for r in evaluate_gates(_payload())}
        # guardrail 67/67 -> CI-alt ~0.947 < 0.99 => GEÇMEDİ (nokta tahmini 1.0!)
        self.assertEqual(rows["G-05"]["olculen"], 1.0)
        self.assertEqual(rows["G-05"]["durum"], "GEÇMEDİ")

    def test_point_estimate_one_does_not_pass(self):
        """Pass-bias'in klasik yolu: "1.000, demek ki gecti". Burada gecmez."""
        rows = {r["gid"]: r for r in evaluate_gates(_payload(fail_closed_rate=1.0))}
        self.assertEqual(rows["C-04"]["olculen"], 1.0)
        # n=45 -> Wilson alt sınır ~0.921 < 1.0 => kapı GEÇMEDİ
        self.assertEqual(rows["C-04"]["durum"], "GEÇMEDİ")

    def test_mean_metric_without_item_values_is_unmeasured(self):
        """Ortalama CI'si item degerleri olmadan UYDURULAMAZ -> ÖLÇÜLMEDİ."""
        rows = {r["gid"]: r for r in evaluate_gates(_payload())}
        self.assertIsNotNone(rows["K-03"]["olculen"])   # deger var
        self.assertIsNone(rows["K-03"]["ci"])           # ama CI yok
        self.assertEqual(rows["K-03"]["durum"], "ÖLÇÜLMEDİ")

    def test_mean_metric_with_item_values_gets_ci(self):
        p = _payload()
        p["items"] = [{"retrieval": {"recall_at_5": v}} for v in
                      [1.0, 1.0, 1.0, 0.9, 1.0, 1.0, 0.95, 1.0, 1.0, 1.0]]
        rows = {r["gid"]: r for r in evaluate_gates(p)}
        self.assertIsNotNone(rows["K-03"]["ci"])
        self.assertIn(rows["K-03"]["durum"], ("GEÇTİ", "GEÇMEDİ"))

    def test_kademe_switches_thresholds(self):
        mvp = {r["gid"]: r["esik"] for r in evaluate_gates(_payload(), "mvp")}
        tam = {r["gid"]: r["esik"] for r in evaluate_gates(_payload(), "tam")}
        self.assertEqual(mvp["A-02"], 0.85)
        self.assertEqual(tam["A-02"], 0.99)

    def test_gate_absent_in_mvp_is_skipped(self):
        rows = {r["gid"]: r for r in evaluate_gates(_payload(), "mvp")}
        self.assertEqual(rows["C-05"]["durum"], "ATLANDI")   # ECE yalnız TAM
        rows_t = {r["gid"]: r for r in evaluate_gates(_payload(), "tam")}
        self.assertNotEqual(rows_t["C-05"]["durum"], "ATLANDI")

    def test_bad_kademe_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_gates(_payload(), "uydurma")

    def test_empty_payload_does_not_crash(self):
        rows = evaluate_gates({})
        self.assertEqual(len(rows), len(GATES))
        self.assertTrue(all(r["durum"] in ("ÖLÇÜLMEDİ", "ATLANDI") for r in rows))


class RenderTests(unittest.TestCase):
    def test_matrix_contains_every_gate_and_a_summary(self):
        md = render_matrix(_payload(), "mvp")
        for g in GATES:
            self.assertIn(g.gid, md)
        self.assertIn("Özet:", md)
        self.assertIn("ÖLÇEN KOD YOK", md)

    def test_matrix_declares_source_of_truth(self):
        """Eşiklerin kilitli belgeden geldiği matriste yazmalı (kural 10)."""
        md = render_matrix(_payload())
        self.assertIn("benchmark.md", md)
        self.assertIn("Kadir", md)

    def test_summary_counts_add_up(self):
        rows = evaluate_gates(_payload())
        s = summary(rows)
        self.assertEqual(sum(s.values()), len(rows))


class ByDimensionTests(unittest.TestCase):
    def test_groups_by_any_field(self):
        items = [{"unite": "U1", "id": "a"}, {"unite": "U1", "id": "b"},
                 {"unite": "U2", "id": "c"}]
        g = by_dimension(items, "unite")
        self.assertEqual(sorted(g), ["U1", "U2"])
        self.assertEqual(len(g["U1"]), 2)

    def test_missing_field_becomes_none_bucket(self):
        g = by_dimension([{"id": "a"}], "senaryo")
        self.assertIn(None, g)


if __name__ == "__main__":
    unittest.main()
