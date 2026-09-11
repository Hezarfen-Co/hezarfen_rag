"""M0-6 (#38) + M0-8 (#40) — tekrar-üretilebilirlik ve izlenebilirlik testleri.

NEDEN (EXP-010/EVAL-13): eval, `generator.answer`ın varsayılanı olan
`temperature=0.2` ile koşuyordu ve seed yoktu. Ölçüldü: aynı 27 item'ın iki
ardışık koşumunda **10/27 item'da üretilen metin değişti**, citation precision'da
Δ 0.033. `OPTIMIZATION.md §H`'nin prompt A/B'sindeki "+0.008 iyileşme" iddiası
bu gürültü bandının ALTINDA — yani o karar istatistiksel olarak desteklenmiyordu.

NEDEN (EVAL-14): sonuç dosyaları hep `eval_v0_*` adıyla yazılıyordu (200-item
v1.1 koşumu bile) ve `meta`'da git SHA / temperature / eşik / açık modüller
yoktu → "hangi kod bu sayıyı üretti" izlenemiyordu.
"""
import os
import unittest
from unittest import mock

from src.eval import runner as R


class TemperatureTests(unittest.TestCase):
    def test_eval_temperature_defaults_to_zero(self):
        """Üretim varsayılanı (0.2) DEĞİŞMEDİ; yalnız ÖLÇÜM determinize edildi."""
        self.assertEqual(R.EVAL_TEMPERATURE, 0.0)

    def test_production_default_is_untouched(self):
        import inspect
        from src.generate.generator import Generator
        sig = inspect.signature(Generator.answer)
        self.assertEqual(sig.parameters["temperature"].default, 0.2)

    def test_eval_passes_temperature_to_generator(self):
        """Asıl iddia: eval çağrısı temperature'ı GEÇİYOR (eskiden geçmiyordu)."""
        seen = {}

        class _Gen:
            abstain_score = 0.30
            ders = "biyoloji"
            context_packing = False
            context_max_tokens = 8000
            safety_classifier = None
            rewriter = None
            deepseek = None

            def answer(self, query, **kw):
                seen.update(kw)
                from src.generate.generator import GroundedAnswer
                return GroundedAnswer(text="cevap [1].", citations=[], abstained=False,
                                      reason="", cost_usd=0.0)

        item = {"id": "t", "soru": "s", "kategori": "orta",
                "beklenen_davranis": "cevapla", "gold_kaynak_spanlar": [],
                "gold_sayfalar": [], "critical": False}
        pl = {"chunks_by_id": {}, "span_meta": {}, "retriever": None,
              "reranker": None, "generator": _Gen(), "doc": None}
        R._eval_item(item, pl, None, set())
        self.assertIn("temperature", seen)
        self.assertEqual(seen["temperature"], 0.0)

    def test_env_override(self):
        """Gerekirse varyans ölçmek için env ile açılabilir (belgelenmiş kaçış).
        NOT: modül yeniden yüklenirken env DEĞİŞİKLİĞİ bitmiş olmalı, aksi hâlde
        0.7 diğer testlere sızar (bu test ilk yazıldığında tam bu oldu)."""
        import importlib
        try:
            with mock.patch.dict(os.environ, {"EVAL_TEMPERATURE": "0.7"}):
                importlib.reload(R)
                self.assertEqual(R.EVAL_TEMPERATURE, 0.7)
        finally:
            importlib.reload(R)       # env temizlendikten SONRA geri yükle
        self.assertEqual(R.EVAL_TEMPERATURE, 0.0)


class SeedTests(unittest.TestCase):
    def test_seed_info_reports_what_was_seeded(self):
        info = R._seed_everything(123)
        self.assertEqual(info["seed"], 123)
        for k in ("numpy", "torch", "torch_deterministic"):
            self.assertIn(k, info)
            self.assertIsInstance(info[k], bool)

    def test_python_random_is_deterministic_after_seed(self):
        import random
        R._seed_everything(7)
        a = [random.random() for _ in range(5)]
        R._seed_everything(7)
        b = [random.random() for _ in range(5)]
        self.assertEqual(a, b)

    def test_numpy_seeded_when_available(self):
        try:
            import numpy as np
        except Exception:
            self.skipTest("numpy yok")
        R._seed_everything(11)
        a = np.random.rand(4).tolist()
        R._seed_everything(11)
        self.assertEqual(a, np.random.rand(4).tolist())

    def test_default_seed_is_fixed_not_random(self):
        self.assertIsInstance(R.EVAL_SEED, int)
        self.assertEqual(R.EVAL_SEED, 20260911)


class TraceabilityTests(unittest.TestCase):
    def test_git_sha_returns_string_or_none(self):
        sha = R._git_sha()
        self.assertTrue(sha is None or isinstance(sha, str))
        if sha:
            self.assertGreaterEqual(len(sha), 7)

    def test_dirty_tree_is_marked(self):
        """Yayınlanmamış değişiklikle ölçülmüş bir sayı ayırt edilebilmeli."""
        sha = R._git_sha()
        if sha is None:
            self.skipTest("git yok")
        import subprocess
        dirty = subprocess.run(["git", "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        self.assertEqual(sha.endswith("-dirty"), bool(dirty))

    def test_md_report_header_carries_mode_and_code_version(self):
        golden = {"version": "v1.1-draft-TASLAK", "items": []}
        overall = {"n": 0, "retrieval": {}, "citation": {},
                   "guardrail_pass_rate": None, "n_guardrail_applicable": 0,
                   "fail_closed_rate": None, "n_abstained": 0, "n_errors": 0,
                   "judge": {"n_judged": 0}}
        md = R._md_report(golden, [], overall, {}, 0.0, "stub", set(), 1.0,
                          mode="oracle_context",
                          golden_path="tests/golden/golden_12kimya_v1.json")
        self.assertIn("golden_12kimya_v1.json", md)
        self.assertIn("v1.1-draft-TASLAK", md)
        self.assertIn("mod=oracle_context", md)
        self.assertIn("temperature=0.0", md)
        # eski sabit başlık artık YOK
        self.assertNotIn("golden_12bio_v0 (", md)

    def test_md_report_defaults_stay_backward_compatible(self):
        golden = {"version": "vX", "items": []}
        overall = {"n": 0, "retrieval": {}, "citation": {},
                   "guardrail_pass_rate": None, "n_guardrail_applicable": 0,
                   "fail_closed_rate": None, "n_abstained": 0, "n_errors": 0,
                   "judge": {"n_judged": 0}}
        md = R._md_report(golden, [], overall, {}, 0.0, "stub", set(), 1.0)
        self.assertIn("mod=end_to_end", md)


if __name__ == "__main__":
    unittest.main()
