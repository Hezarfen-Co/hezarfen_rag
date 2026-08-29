"""Birim testleri — maliyet hesabı (src.pricing). Ağ/anahtar gerektirmez."""
import unittest

from src.pricing import Usage, cost_usd, resolve, PRICING


class PricingTests(unittest.TestCase):
    def test_cost_math_exact(self):
        # deepseek-chat -> v4-flash: (6000*0.014 + 14000*0.44 + 3000*1.32)/1e6
        u = Usage(input_cache_hit=6000, input_cache_miss=14000, output=3000)
        self.assertAlmostEqual(cost_usd("deepseek-chat", u), 0.010204, places=6)

    def test_offpeak_is_half(self):
        u = Usage(input_cache_miss=10000, output=2000)
        peak = cost_usd("deepseek-chat", u, "peak")
        off = cost_usd("deepseek-chat", u, "offpeak")
        self.assertAlmostEqual(off, peak * 0.5, places=9)

    def test_alias_resolves(self):
        self.assertEqual(resolve("deepseek-chat"), "deepseek-v4-flash")
        self.assertEqual(resolve("deepseek-reasoner"), "deepseek-v4-pro")

    def test_unknown_model_raises(self):
        with self.assertRaises(KeyError):
            cost_usd("gpt-yok", Usage(output=1))

    def test_usage_from_api_cache_split(self):
        u = Usage.from_api({"prompt_cache_hit_tokens": 100,
                            "prompt_cache_miss_tokens": 900,
                            "completion_tokens": 200,
                            "completion_tokens_details": {"reasoning_tokens": 50}})
        self.assertEqual((u.input_cache_hit, u.input_cache_miss, u.output, u.reasoning),
                         (100, 900, 200, 50))

    def test_usage_from_api_no_cache_is_conservative(self):
        # cache alanı yoksa tüm prompt cache-miss (en pahalı) sayılmalı
        u = Usage.from_api({"prompt_tokens": 500, "completion_tokens": 100})
        self.assertEqual((u.input_cache_hit, u.input_cache_miss), (0, 500))

    def test_pricing_table_shape(self):
        for m, p in PRICING.items():
            self.assertLessEqual(p["in_hit"], p["in_miss"], f"{m}: hit>miss olmamalı")
            self.assertLessEqual(p["in_miss"], p["out"], f"{m}: miss>out beklenir")


if __name__ == "__main__":
    unittest.main()
