"""M0-1 (#33) — güven aralığı + kapı kararı testleri.

NEDEN bu dosya var: `benchmark.md`'nin açık kuralı "ortalama skor DEĞİL, %95 güven
aralığının ALT sınırı kapıyı geçmeli". Bu kural bugüne kadar KODDA YOKTU; §H ve
deney kayıtları nokta tahmini raporluyordu. EXP-010/EVAL-03 bunun somut sonucunu
ölçtü: guardrail "33/33 = 1.000" görünüyor ama %95 CI alt sınırı 0.896 — yani
%10'a kadar gerçek hata oranıyla uyumlu.

Bu testler iki şeyi SABİTLER:
1. Bilinen sayılar (33/33 -> 0.896, n_needed(0.99) -> 381) regresyona karşı kilitli.
2. `gate_status` CI olmadan "GEÇTİ" DÖNDÜREMEZ — pass-bias'ın kapıya sızdığı yol
   buydu; artık kodla imkânsız.
"""
import unittest

from src.eval.metrics import (Z_95, bootstrap_ci, gate_status, n_needed_for_gate,
                              wilson_ci)


class WilsonTests(unittest.TestCase):
    def test_33_of_33_lower_bound_is_not_one(self):
        """EXP-010/EVAL-03'ün çekirdek bulgusu: kusursuz skor kapıyı geçmiyor."""
        lo, hi = wilson_ci(33, 33)
        self.assertAlmostEqual(lo, 0.896, places=3)
        self.assertEqual(hi, 1.0)
        # ölçülen guardrail kapısı 0.99 -> CI-alt 0.896 < 0.99 => GEÇMEDİ
        self.assertEqual(gate_status(0.99, (lo, hi)), "GEÇMEDİ")

    def test_12_of_12_lower_bound(self):
        """prompt_injection 12/12 -> 0.7575 (kapı 0.99'un çok altında).
        EXP-010 raporunda 0.757 olarak kısaltılmıştı; kesin değer 0.75751."""
        lo, _ = wilson_ci(12, 12)
        self.assertAlmostEqual(lo, 0.75751, places=5)

    def test_normal_approximation_would_have_hidden_this(self):
        """Karşılaştırma: normal-yaklaşım k==n'de [1.0, 1.0] verir (yanıltıcı).
        Wilson'ın var olma gerekçesi bu — testte açıkça duruyor."""
        p = 33 / 33
        naive_half = Z_95 * ((p * (1 - p) / 33) ** 0.5)
        self.assertEqual(naive_half, 0.0)          # naive: aralık YOK, "kesin 1.0"
        self.assertLess(wilson_ci(33, 33)[0], 1.0)  # Wilson: dürüst alt sınır

    def test_half_and_half_is_centered(self):
        lo, hi = wilson_ci(50, 100)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)
        self.assertAlmostEqual((lo + hi) / 2, 0.5, places=6)

    def test_zero_successes(self):
        lo, hi = wilson_ci(0, 20)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.0)      # üst sınır 0 DEĞİL (belirsizlik korunur)

    def test_n_zero_is_unmeasured_not_zero(self):
        """n=0 -> None. 0.0 ile KARIŞTIRILMAZ ('ölçülmedi' != 'başarısız')."""
        self.assertIsNone(wilson_ci(0, 0))

    def test_wider_interval_for_smaller_n(self):
        w_small = wilson_ci(9, 10)
        w_large = wilson_ci(90, 100)
        self.assertGreater(w_small[1] - w_small[0], w_large[1] - w_large[0])

    def test_invalid_k(self):
        with self.assertRaises(ValueError):
            wilson_ci(5, 3)
        with self.assertRaises(ValueError):
            wilson_ci(-1, 3)


class NeededSampleTests(unittest.TestCase):
    def test_n_for_099_gate(self):
        """EVAL-03'ün sayısı: sıfır hatayla CI-alt >= 0.99 için n = 381."""
        self.assertEqual(n_needed_for_gate(0.99), 381)

    def test_n_for_095_gate(self):
        self.assertEqual(n_needed_for_gate(0.95), 73)

    def test_returned_n_actually_passes(self):
        for th in (0.90, 0.95, 0.98, 0.99):
            n = n_needed_for_gate(th)
            self.assertGreaterEqual(wilson_ci(n, n)[0], th)
            self.assertLess(wilson_ci(n - 1, n - 1)[0], th)   # n-1 yetmiyor

    def test_out_of_range_threshold(self):
        for bad in (0.0, 1.0, -0.1, 1.5):
            with self.assertRaises(ValueError):
                n_needed_for_gate(bad)


class BootstrapTests(unittest.TestCase):
    def test_constant_values_give_degenerate_interval(self):
        lo, hi = bootstrap_ci([0.8] * 30, n_boot=500)
        self.assertAlmostEqual(lo, 0.8, places=9)
        self.assertAlmostEqual(hi, 0.8, places=9)

    def test_interval_contains_mean(self):
        vals = [0.6, 0.7, 0.8, 0.9, 1.0, 0.5, 0.85, 0.95, 0.75, 0.65]
        lo, hi = bootstrap_ci(vals, n_boot=2000)
        m = sum(vals) / len(vals)
        self.assertLessEqual(lo, m)
        self.assertGreaterEqual(hi, m)

    def test_deterministic_with_fixed_seed(self):
        vals = [0.1, 0.4, 0.9, 0.3, 0.7]
        self.assertEqual(bootstrap_ci(vals, n_boot=800),
                         bootstrap_ci(vals, n_boot=800))

    def test_nones_ignored_like_mean(self):
        self.assertEqual(bootstrap_ci([0.5, None, 0.5, None], n_boot=300),
                         bootstrap_ci([0.5, 0.5], n_boot=300))

    def test_too_few_observations(self):
        """Tek gözlemden aralık üretmek uydurma olurdu -> None."""
        self.assertIsNone(bootstrap_ci([0.9], n_boot=100))
        self.assertIsNone(bootstrap_ci([], n_boot=100))
        self.assertIsNone(bootstrap_ci([None, None], n_boot=100))


class GateStatusTests(unittest.TestCase):
    def test_passes_only_on_lower_bound(self):
        self.assertEqual(gate_status(0.90, (0.91, 0.99)), "GEÇTİ")
        self.assertEqual(gate_status(0.90, (0.89, 0.99)), "GEÇMEDİ")

    def test_point_estimate_cannot_pass_a_gate(self):
        """Pass-bias'ın kapıya sızdığı yol: nokta tahmini 1.0 ama CI yok.
        Bu fonksiyonla "GEÇTİ" demek İMKÂNSIZ olmalı."""
        self.assertEqual(gate_status(0.99, None), "ÖLÇÜLMEDİ")

    def test_lower_is_better_metrics_use_upper_bound(self):
        # halüsinasyon oranı <= 0.05 gibi metrikler
        self.assertEqual(gate_status(0.05, (0.00, 0.04), higher_is_better=False),
                         "GEÇTİ")
        self.assertEqual(gate_status(0.05, (0.00, 0.06), higher_is_better=False),
                         "GEÇMEDİ")

    def test_boundary_is_inclusive(self):
        self.assertEqual(gate_status(0.90, (0.90, 0.95)), "GEÇTİ")
        self.assertEqual(gate_status(0.05, (0.01, 0.05), higher_is_better=False),
                         "GEÇTİ")

    def test_real_measurements_from_exp010(self):
        """EXP-010'da hesaplanan gerçek değerler — hiçbiri kapısını geçmiyor.
        Bu test, "kapı geçildi" iddiasının kodla çürütülebildiğini gösterir."""
        cases = [
            # (metrik, kapı, ölçülen CI, beklenen)
            ("guardrail zararlı 33/33", 0.99, wilson_ci(33, 33), "GEÇMEDİ"),
            ("injection 12/12", 0.99, wilson_ci(12, 12), "GEÇMEDİ"),
            ("faithfulness 0.988 (n=21)", 0.99, (0.964, 1.000), "GEÇMEDİ"),
            ("citation recall 0.883", 0.97, (0.835, 0.929), "GEÇMEDİ"),
            ("retrieval recall@20 0.961", 0.98, (0.933, 0.985), "GEÇMEDİ"),
        ]
        for label, gate, ci, expected in cases:
            with self.subTest(label):
                self.assertEqual(gate_status(gate, ci), expected)


if __name__ == "__main__":
    unittest.main()
