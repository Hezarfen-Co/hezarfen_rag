"""Birim testleri -- src.eval.metrics (DETERMINISTIK, LLM gerektirmez).

Amac: pass-bias YOK -- her test BILINEN girdi -> ELDE HESAPLANMIS beklenen
cikti dogrular (formul dogrulugu), rastgele/gercek pipeline verisi KULLANILMAZ.
"""
import unittest

from src.eval.metrics import (
    mean, recall_at_k, precision_at_k, mrr, page_range_set,
    compute_retrieval_metrics, citation_precision_recall,
    guardrail_pass, is_fail_closed,
)


class MeanTests(unittest.TestCase):
    def test_ignores_none(self):
        self.assertAlmostEqual(mean([1.0, 2.0, None, 3.0]), 2.0)

    def test_all_none_is_none(self):
        self.assertIsNone(mean([None, None]))

    def test_empty_is_none(self):
        self.assertIsNone(mean([]))


class RecallPrecisionMrrTests(unittest.TestCase):
    """Sentetik siralanmis kume listesi: ranked[i] = i'inci retrieved chunk'in
    tasidigi span_id kumesi (0-indeksli, en alakali ilk sirada)."""

    def setUp(self):
        self.ranked = [
            {"s1"},          # rank 1 -- gold'da yok
            {"s2", "s3"},    # rank 2 -- s2 gold'da VAR (ilk isabet)
            {"s4"},          # rank 3 -- gold'da yok
            set(),           # rank 4 -- bos (retrieved ama span yok)
            {"s5"},          # rank 5 -- s5 gold'da VAR
        ]
        self.gold = {"s2", "s5"}

    def test_recall_at_1_no_hit_yet(self):
        # ilk 1 elemanin kumesi {s1}; gold {s2,s5} ile kesisim bos -> 0/2
        self.assertEqual(recall_at_k(self.ranked, self.gold, 1), 0.0)

    def test_recall_at_2_one_of_two_gold_covered(self):
        # ilk 2 elemanin birlesimi {s1,s2,s3}; gold'dan yalniz s2 kapsandi -> 1/2
        self.assertEqual(recall_at_k(self.ranked, self.gold, 2), 0.5)

    def test_recall_at_5_all_gold_covered(self):
        # ilk 5 (hepsi) birlesimi {s1,s2,s3,s4,s5}; gold'un ikisi de kapsandi -> 2/2
        self.assertEqual(recall_at_k(self.ranked, self.gold, 5), 1.0)

    def test_recall_undefined_when_gold_empty(self):
        self.assertIsNone(recall_at_k(self.ranked, set(), 5))

    def test_precision_at_2(self):
        # ilk 2 chunk: {s1}(isabetsiz), {s2,s3}(isabetli) -> 1/2 isabetli
        self.assertEqual(precision_at_k(self.ranked, self.gold, 2), 0.5)

    def test_precision_at_5(self):
        # 5 chunk icinde isabetli olanlar: rank2 ({s2,s3}) ve rank5 ({s5}) -> 2/5
        self.assertEqual(precision_at_k(self.ranked, self.gold, 5), 0.4)

    def test_precision_undefined_when_gold_empty(self):
        self.assertIsNone(precision_at_k(self.ranked, set(), 5))

    def test_precision_with_fewer_items_than_k(self):
        # k=10 ama yalniz 5 retrieved var -> mevcut 5 uzerinden hesapla (2/5)
        self.assertEqual(precision_at_k(self.ranked, self.gold, 10), 0.4)

    def test_mrr_first_hit_at_rank_2(self):
        # ilk isabet rank2'de (1-indeksli) -> 1/2
        self.assertEqual(mrr(self.ranked, self.gold), 0.5)

    def test_mrr_zero_when_no_hit(self):
        self.assertEqual(mrr(self.ranked, {"yok"}), 0.0)

    def test_mrr_undefined_when_gold_empty(self):
        self.assertIsNone(mrr(self.ranked, set()))

    def test_mrr_rank_1_hit(self):
        ranked = [{"g1"}, {"g2"}]
        self.assertEqual(mrr(ranked, {"g1"}), 1.0)


class PageRangeSetTests(unittest.TestCase):
    def test_simple_range(self):
        self.assertEqual(page_range_set(3, 5), {3, 4, 5})

    def test_single_page(self):
        self.assertEqual(page_range_set(7, 7), {7})

    def test_reversed_bounds_still_works(self):
        self.assertEqual(page_range_set(9, 6), {6, 7, 8, 9})

    def test_none_bounds_is_empty(self):
        self.assertEqual(page_range_set(None, None), set())


class ComputeRetrievalMetricsTests(unittest.TestCase):
    def test_wraps_span_and_page_metrics(self):
        span_sets = [{"a"}, {"b"}]
        page_sets = [{1}, {2}]
        gold_spans = {"b"}
        gold_pages = {2}
        m = compute_retrieval_metrics(span_sets, page_sets, gold_spans, gold_pages)
        self.assertEqual(m.recall_at_10, 1.0)
        self.assertEqual(m.recall_at_20, 1.0)
        self.assertEqual(m.mrr_value, 0.5)          # ilk isabet rank2 -> 1/2
        self.assertEqual(m.page_recall_at_10, 1.0)
        self.assertEqual(m.page_mrr_value, 0.5)
        self.assertEqual(m.n_retrieved, 2)

    def test_edge_case_no_gold_spans_returns_none_everywhere(self):
        m = compute_retrieval_metrics([{"a"}], [{1}], set(), set())
        self.assertIsNone(m.recall_at_10)
        self.assertIsNone(m.precision_at_10)
        self.assertIsNone(m.mrr_value)
        self.assertIsNone(m.page_recall_at_10)


class CitationPrecisionRecallTests(unittest.TestCase):
    def test_partial_overlap(self):
        # gold={a,b,c}, cited={a,x} -> inter={a} -> precision=1/2, recall=1/3
        m = citation_precision_recall({"a", "x"}, {"a", "b", "c"})
        self.assertAlmostEqual(m.precision, 0.5)
        self.assertAlmostEqual(m.recall, 1 / 3)
        self.assertEqual(m.n_cited_spans, 2)
        self.assertEqual(m.n_gold_spans, 3)

    def test_perfect_match(self):
        m = citation_precision_recall({"a", "b"}, {"a", "b"})
        self.assertEqual(m.precision, 1.0)
        self.assertEqual(m.recall, 1.0)

    def test_no_gold_is_undefined(self):
        m = citation_precision_recall({"a"}, set())
        self.assertIsNone(m.precision)
        self.assertIsNone(m.recall)

    def test_no_citations_but_gold_exists_recall_zero_precision_undefined(self):
        m = citation_precision_recall(set(), {"a", "b"})
        self.assertIsNone(m.precision)
        self.assertEqual(m.recall, 0.0)

    def test_no_overlap_at_all(self):
        m = citation_precision_recall({"x", "y"}, {"a", "b"})
        self.assertEqual(m.precision, 0.0)
        self.assertEqual(m.recall, 0.0)

    def test_pages_none_when_not_given_backward_compat(self):
        m = citation_precision_recall({"a", "x"}, {"a", "b", "c"})
        self.assertIsNone(m.precision_page)
        self.assertIsNone(m.recall_page)

    def test_page_level_fixes_span_granularity_artifact(self):
        # Model DOĞRU chunk'ı atıflıyor: chunk 5 span taşır (s1..s5), gold sadece s1.
        # span-level precision düşük (1/5) AMA sayfa doğru (sayfa 20) -> sayfa P/R=1.0.
        m = citation_precision_recall(
            {"s1", "s2", "s3", "s4", "s5"}, {"s1"},
            cited_pages={20}, gold_pages={20})
        self.assertAlmostEqual(m.precision, 0.2)          # span-level yanıltıcı düşük
        self.assertEqual(m.recall, 1.0)
        self.assertEqual(m.precision_page, 1.0)           # sayfa-level ürün-gerçeği
        self.assertEqual(m.recall_page, 1.0)
        self.assertEqual(m.n_cited_pages, 1)
        self.assertEqual(m.n_gold_pages, 1)

    def test_page_level_wrong_page(self):
        m = citation_precision_recall({"s9"}, {"s1"}, cited_pages={99}, gold_pages={20})
        self.assertEqual(m.precision_page, 0.0)
        self.assertEqual(m.recall_page, 0.0)

    def test_page_level_no_citation_recall_zero(self):
        m = citation_precision_recall(set(), {"s1"}, cited_pages=set(), gold_pages={20})
        self.assertIsNone(m.precision_page)
        self.assertEqual(m.recall_page, 0.0)


class GuardrailPassTests(unittest.TestCase):
    def test_cekimser_expected_and_abstained_passes(self):
        self.assertTrue(guardrail_pass("cekimser", True, "insufficient_data"))

    def test_cekimser_expected_but_answered_fails(self):
        self.assertFalse(guardrail_pass("cekimser", False, ""))

    def test_red_expected_and_guard_triggered_passes(self):
        self.assertTrue(guardrail_pass("red", True, "guard_self_harm"))

    def test_red_expected_but_only_insufficient_data_fails(self):
        # abstained=True ama guard HIC tetiklenmedi (rastlantisal fail-closed) -> basarisiz
        self.assertFalse(guardrail_pass("red", True, "insufficient_data"))

    def test_red_expected_but_answered_fails(self):
        self.assertFalse(guardrail_pass("red", False, ""))

    def test_red_expected_guard_output_passes(self):
        self.assertTrue(guardrail_pass("red", True, "guard_output"))

    def test_cevapla_is_not_applicable(self):
        self.assertIsNone(guardrail_pass("cevapla", False, ""))
        self.assertIsNone(guardrail_pass("cevapla", True, "insufficient_data"))


class FailClosedTests(unittest.TestCase):
    def test_not_abstained_is_not_applicable(self):
        self.assertIsNone(is_fail_closed(False, 0.01))

    def test_abstained_with_zero_cost_is_fail_closed(self):
        self.assertTrue(is_fail_closed(True, 0.0))

    def test_abstained_with_nonzero_cost_is_not_fail_closed(self):
        # LLM cagrildi (ör. guard_output/model_abstained) -- fail-closed DEGIL
        self.assertFalse(is_fail_closed(True, 0.0042))


if __name__ == "__main__":
    unittest.main()
