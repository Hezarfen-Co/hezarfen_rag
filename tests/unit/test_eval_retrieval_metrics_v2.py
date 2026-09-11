"""M0-3 (#35) — recall@5 · nDCG@10 · all_evidence_recall testleri.

NEDEN bu dosya var (EXP-010/EVAL-08): `OPTIMIZATION.md §H`'nin STANDING KARAR'ı
"retrieval değerlendirmesinde birincil metrikler **recall@5/@10 + MRR**" diyor,
ama `RetrievalMetrics`'te yalnız @10/@20 vardı; **recall@5 ve nDCG kodda YOKTU**.
Sonuç: ölçülen `recall@20` doygun (%92 item'da tam 1.0) → sıralama kalitesi ve
reranker kazancı hiç ölçülemiyordu (`benchmark.md §5` zorunlu ablation açık kaldı).

Ayrıca EVAL-10: `recall_at_k` kısmi kredi veriyor; çok-adımlı soruda kanıtın bir
parçası eksikse cevap üretilemez → `all_evidence_recall_at_k` ikili ölçer.

Beklenen değerler ELLE hesaplanmıştır (aşağıdaki yorumlarda gösteriliyor) —
kodun kendi çıktısıyla doğrulanmamıştır (pass-bias yasağı).
"""
import math
import unittest

from src.eval.metrics import (all_evidence_recall_at_k, compute_retrieval_metrics,
                              ndcg_at_k, precision_at_k, recall_at_k)


class RecallAt5Tests(unittest.TestCase):
    def test_hit_inside_and_outside_top5(self):
        ranked = [{"x"}, {"x"}, {"x"}, {"x"}, {"a"}, {"b"}]
        # gold {a,b}: ilk 5'te yalnız a var -> 1/2 ; ilk 10'da ikisi -> 2/2
        self.assertAlmostEqual(recall_at_k(ranked, {"a", "b"}, 5), 0.5)
        self.assertAlmostEqual(recall_at_k(ranked, {"a", "b"}, 10), 1.0)

    def test_at5_is_stricter_than_at20(self):
        """@20 doygunluğunun neden metrik körlüğü olduğunu gösteren test."""
        ranked = [{"x"}] * 15 + [{"a"}]
        self.assertAlmostEqual(recall_at_k(ranked, {"a"}, 5), 0.0)
        self.assertAlmostEqual(recall_at_k(ranked, {"a"}, 20), 1.0)

    def test_gold_empty_is_none(self):
        self.assertIsNone(recall_at_k([{"a"}], set(), 5))


class NdcgTests(unittest.TestCase):
    def test_perfect_ranking_is_one(self):
        # rels=[1,1,0] -> DCG = 1/log2(2) + 1/log2(3) = 1 + 0.63093 = 1.63093
        # n_rel_total=2 -> IDCG aynı -> 1.0
        ranked = [{"a"}, {"b"}, {"x"}]
        self.assertAlmostEqual(ndcg_at_k(ranked, {"a", "b"}, 10), 1.0, places=9)

    def test_hit_miss_hit(self):
        # rels=[1,0,1] -> DCG = 1 + 0 + 1/log2(4) = 1 + 0.5 = 1.5
        # n_rel_total=2 -> IDCG = 1 + 1/log2(3) = 1.6309297535714575
        # nDCG = 1.5 / 1.6309297535714575 = 0.9197207891481876
        ranked = [{"a"}, {"x"}, {"b"}]
        expected = 1.5 / (1.0 + 1.0 / math.log2(3))
        self.assertAlmostEqual(ndcg_at_k(ranked, {"a", "b"}, 10), expected, places=9)
        self.assertAlmostEqual(expected, 0.91972, places=5)

    def test_single_hit_at_rank3(self):
        # rels=[0,0,1] -> DCG = 1/log2(4) = 0.5 ; n_rel_total=1 -> IDCG = 1.0
        ranked = [{"x"}, {"y"}, {"a"}]
        self.assertAlmostEqual(ndcg_at_k(ranked, {"a"}, 10), 0.5, places=9)

    def test_ranking_order_matters(self):
        """recall aynı kalırken nDCG ayrışıyor — metriğin var olma gerekçesi."""
        good = [{"a"}, {"x"}, {"y"}]
        bad = [{"x"}, {"y"}, {"a"}]
        self.assertEqual(recall_at_k(good, {"a"}, 10), recall_at_k(bad, {"a"}, 10))
        self.assertGreater(ndcg_at_k(good, {"a"}, 10), ndcg_at_k(bad, {"a"}, 10))

    def test_no_hits_is_zero(self):
        self.assertEqual(ndcg_at_k([{"x"}, {"y"}], {"a"}, 10), 0.0)

    def test_gold_empty_is_none(self):
        self.assertIsNone(ndcg_at_k([{"a"}], set(), 10))

    def test_k_truncation_uses_ideal_within_k(self):
        # k=1, isabet 1. sırada: DCG=1 ; n_ideal=min(1, n_rel_total=2)=1 -> IDCG=1
        ranked = [{"a"}, {"b"}]
        self.assertAlmostEqual(ndcg_at_k(ranked, {"a", "b"}, 1), 1.0, places=9)
        # k=1, isabet 2. sırada (top-1'de yok): DCG=0 -> 0.0
        self.assertAlmostEqual(ndcg_at_k([{"x"}, {"a"}], {"a"}, 1), 0.0, places=9)

    def test_never_exceeds_one(self):
        for ranked in ([{"a"}], [{"a"}, {"b"}], [{"a"}, {"x"}, {"b"}, {"y"}]):
            v = ndcg_at_k(ranked, {"a", "b"}, 10)
            self.assertLessEqual(v, 1.0 + 1e-12)
            self.assertGreaterEqual(v, 0.0)


class AllEvidenceRecallTests(unittest.TestCase):
    def test_all_gold_covered(self):
        self.assertEqual(all_evidence_recall_at_k([{"a"}, {"b"}], {"a", "b"}, 10), 1.0)

    def test_partial_coverage_scores_zero(self):
        """Kısmi kredi YOK: 2 gold span'dan 1'i -> 0.0 (recall_at_k 0.5 derdi)."""
        ranked = [{"a"}, {"x"}]
        self.assertEqual(all_evidence_recall_at_k(ranked, {"a", "b"}, 10), 0.0)
        self.assertAlmostEqual(recall_at_k(ranked, {"a", "b"}, 10), 0.5)

    def test_k_cutoff_respected(self):
        ranked = [{"a"}, {"b"}]
        self.assertEqual(all_evidence_recall_at_k(ranked, {"a", "b"}, 1), 0.0)
        self.assertEqual(all_evidence_recall_at_k(ranked, {"a", "b"}, 2), 1.0)

    def test_single_span_gold_matches_recall(self):
        ranked = [{"x"}, {"a"}]
        self.assertEqual(all_evidence_recall_at_k(ranked, {"a"}, 10), 1.0)
        self.assertEqual(recall_at_k(ranked, {"a"}, 10), 1.0)

    def test_one_chunk_carrying_all_gold_spans(self):
        """Bir chunk birden çok span_id taşıyabilir (chunker sözleşmesi)."""
        self.assertEqual(all_evidence_recall_at_k([{"a", "b", "c"}], {"a", "b"}, 10), 1.0)

    def test_gold_empty_is_none(self):
        self.assertIsNone(all_evidence_recall_at_k([{"a"}], set(), 10))


class ComputeRetrievalMetricsTests(unittest.TestCase):
    def _mk(self):
        spans = [{"s1"}, {"x"}, {"s2"}, {"y"}, {"z"}, {"w"}]
        pages = [{10}, {99}, {11}, {98}, {97}, {96}]
        return compute_retrieval_metrics(spans, pages, {"s1", "s2"}, {10, 11})

    def test_new_fields_present_and_correct(self):
        m = self._mk()
        # ilk 5'te s1(0) ve s2(2) var -> recall@5 = 1.0
        self.assertAlmostEqual(m.recall_at_5, 1.0)
        self.assertAlmostEqual(m.page_recall_at_5, 1.0)
        # rels=[1,0,1,0,0,0] -> DCG=1.5 ; IDCG=1+1/log2(3) -> 0.91972
        self.assertAlmostEqual(m.ndcg_at_10, 1.5 / (1.0 + 1.0 / math.log2(3)), places=9)
        self.assertEqual(m.all_evidence_recall_at_10, 1.0)
        self.assertEqual(m.all_evidence_recall_at_20, 1.0)
        self.assertEqual(m.n_gold_spans, 2)
        self.assertEqual(m.n_gold_pages, 2)

    def test_precision_at_5_added(self):
        m = self._mk()
        # ilk 5 chunk'tan 2'si isabetli -> 0.4
        self.assertAlmostEqual(m.precision_at_5, 0.4)
        self.assertAlmostEqual(precision_at_k([{"s1"}, {"x"}, {"s2"}, {"y"}, {"z"}],
                                              {"s1", "s2"}, 5), 0.4)

    def test_backward_compatible_fields_unchanged(self):
        """Mevcut kayıtlarla kıyaslanabilirlik: eski alanlar aynı kalmalı."""
        m = self._mk()
        self.assertAlmostEqual(m.recall_at_10, 1.0)
        self.assertAlmostEqual(m.recall_at_20, 1.0)
        self.assertAlmostEqual(m.mrr_value, 1.0)          # ilk isabet 1. sırada
        self.assertEqual(m.n_retrieved, 6)

    def test_all_evidence_zero_when_second_span_missing(self):
        m = compute_retrieval_metrics([{"s1"}, {"x"}], [{10}, {99}],
                                      {"s1", "s2"}, {10, 11})
        self.assertAlmostEqual(m.recall_at_10, 0.5)        # kısmi kredi
        self.assertEqual(m.all_evidence_recall_at_10, 0.0)  # ikili: başarısız

    def test_runner_keys_match_dataclass(self):
        """`runner._RETRIEVAL_KEYS` ile dataclass alanları uyumsuz kalmasın —
        uyumsuzluk sessizce None ortalamasına yol açar."""
        from dataclasses import fields
        from src.eval.runner import _RETRIEVAL_KEYS
        names = {f.name for f in fields(self._mk())}
        for k in _RETRIEVAL_KEYS:
            self.assertIn(k, names, f"runner {k} istiyor ama RetrievalMetrics'te yok")


if __name__ == "__main__":
    unittest.main()
