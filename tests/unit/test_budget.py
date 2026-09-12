"""#79 (EXP-010/OPS-05) — maliyet tavanı, ENGELLEYİCİ.

ÖLÇÜLEN DURUM: `costlog.record()` yalnız **yazıyordu**; hiçbir çağıran dönüş
değerine bakıp reddetmiyordu. Kullanıcı kotası, günlük USD tavanı yoktu.
Ölçülen sömürü yolları:
  * `/rag/questions n=100000` → şema kabul etti, handler'a 100000 olarak ulaştı
  * `/rag/chat options={"top_n":100000,"candidate_n":100000}` → HTTP 200
  * **tek istekte yüzlerce LLM çağrısı:** `scope.pages=[1..187]` özet
İlk ikisi #48'de Pydantic sınırlarıyla kapandı; burası kalan iki katman.
"""
import unittest

from src.budget import (BudgetGate, check_request_size, estimate_llm_calls)


class CallEstimateTests(unittest.TestCase):
    """Özyinelemeli hiyerarşik özet kaç çağrı yapar — İSTEK KABUL EDİLMEDEN."""

    def test_small_scope_is_one_call(self):
        for n in (1, 5, 12):
            self.assertEqual(estimate_llm_calls(n), 1, n)

    def test_just_over_the_group_size_needs_a_merge(self):
        # 13 birim -> 2 ara-özet + 1 birleştirme
        self.assertEqual(estimate_llm_calls(13), 3)

    def test_the_measured_exploit_is_quantified(self):
        """Denetimde ölçülen `scope.pages=[1..187]` senaryosu.

        DİKKAT: 187 SAYFA, 187 birim değil. İlk testimde bunları karıştırıp
        187'yi birim sanmıştım. Gerçek kitapla ölçüldü: 194 sayfa = 2.740
        birim → **252 LLM çağrısı** ("onlarca-yüzlerce" iddiası doğrulandı)."""
        self.assertEqual(estimate_llm_calls(2740), 252)
        self.assertEqual(estimate_llm_calls(187), 19)      # 187 BİRİM olsaydı

    def test_empty_scope_is_zero(self):
        self.assertEqual(estimate_llm_calls(0), 0)
        self.assertEqual(estimate_llm_calls(-5), 0)

    def test_group_size_changes_the_count(self):
        self.assertGreater(estimate_llm_calls(100, 4), estimate_llm_calls(100, 12))


class RequestSizeGateTests(unittest.TestCase):
    def test_whole_book_is_rejected(self):
        """Denetimdeki sömürü GERÇEK KİTAPLA ölçüldü: 194 sayfa = 2.740 birim,
        58.649 token, **252 LLM çağrısı**."""
        k = check_request_size(2740, n_tokens=58649)
        self.assertFalse(k.allowed)
        self.assertEqual(k.reason, "scope_too_large")

    def test_normal_scope_passes(self):
        self.assertTrue(check_request_size(12).allowed)
        self.assertTrue(check_request_size(40).allowed)

    def test_real_chapter_summaries_must_pass(self):
        """REGRESYON KORUMASI — bu hatayı GERÇEKTEN yaptım.

        İlk sürümde `MAX_UNITS_PER_REQUEST=60` idi çünkü "birim"i chunk
        sanmıştım; oysa birim bir METİN BLOĞU (~11,6 blok/sayfa), yani 60
        birim ≈ **5 sayfa**. Ürün gösteriminde **6 sayfalık normal bir özet
        bile reddedildi** — çekirdek bir özelliği kırmıştım ve bunu ancak
        gerçek koşumda gördüm.

        Ölçülen gerçek değerler (10-biyoloji):
          12 sayfa → 141 birim / 1.812 token / 13 çağrı
          30 sayfa → 363 birim / 7.132 token / 35 çağrı
        """
        for sayfa, birim, token in ((6, 41, 796), (12, 141, 1812), (30, 363, 7132)):
            with self.subTest(sayfa=sayfa):
                k = check_request_size(birim, n_tokens=token)
                self.assertTrue(k.allowed,
                                f"{sayfa} sayfalık normal özet reddedildi")

    def test_token_ceiling_is_the_primary_measure(self):
        """Para token'da harcanıyor; birim ve çağrı ucuz ön-elemedir."""
        k = check_request_size(10, n_tokens=99_999)
        self.assertFalse(k.allowed)
        self.assertEqual(k.spent_usd, 99_999)

    def test_token_check_is_skipped_when_not_provided(self):
        self.assertTrue(check_request_size(10).allowed)

    def test_unit_ceiling_is_enforced_separately_from_calls(self):
        """İki ayrı tavan: birim sayısı VE çağrı sayısı. Biri diğerini
        kapsamaz — küçük gruplarla az birim de çok çağrı üretebilir."""
        k = check_request_size(30, max_units=20, max_calls=999)
        self.assertFalse(k.allowed)
        k2 = check_request_size(30, max_units=999, max_calls=2,
                                max_units_per_group=4)
        self.assertFalse(k2.allowed)

    def test_zero_disables_a_ceiling(self):
        self.assertTrue(check_request_size(10_000, max_units=0, max_calls=0).allowed)


class BudgetGateTests(unittest.TestCase):
    def setUp(self):
        self.g = BudgetGate(user_daily_usd=1.0, tenant_monthly_usd=10.0,
                            soft_ratio=0.8)

    def test_empty_budget_allows(self):
        self.assertTrue(self.g.check(user="u1").allowed)

    def test_soft_threshold_warns_but_allows(self):
        """Tek eşik yetmez: %80'de uyarmak operatöre zaman kazandırır,
        %100'de reddetmek ürünü korur."""
        self.g.record(0.85, user="u1")
        k = self.g.check(user="u1")
        self.assertTrue(k.allowed)
        self.assertTrue(k.soft)

    def test_hard_ceiling_denies(self):
        self.g.record(1.05, user="u1")
        k = self.g.check(user="u1")
        self.assertFalse(k.allowed)
        self.assertEqual(k.reason, "budget_exceeded")
        self.assertEqual(k.scope, "user")

    def test_one_user_does_not_block_another(self):
        self.g.record(5.0, user="u1")
        self.assertFalse(self.g.check(user="u1").allowed)
        self.assertTrue(self.g.check(user="u2").allowed)

    def test_tenant_ceiling_is_separate(self):
        self.g.record(11.0, tenant="okul1")
        self.assertFalse(self.g.check(tenant="okul1").allowed)
        self.assertTrue(self.g.check(user="u1").allowed)

    def test_daily_counter_resets_next_day(self):
        import time
        simdi = time.time()
        self.g.record(2.0, user="u1", ts=simdi)
        self.assertFalse(self.g.check(user="u1", ts=simdi).allowed)
        self.assertTrue(self.g.check(user="u1", ts=simdi + 86400 * 2).allowed)

    def test_zero_limit_means_disabled(self):
        g = BudgetGate(user_daily_usd=0.0, tenant_monthly_usd=0.0)
        g.record(999.0, user="u1")
        self.assertTrue(g.check(user="u1").allowed)

    def test_anonymous_request_is_not_charged(self):
        """Kullanıcı kimliği yoksa sayaç tutulamaz; istek geçer. Bu bilinçli:
        tavan bir GÜVENLİK kontrolü değil, maliyet kontrolüdür."""
        self.g.record(5.0)
        self.assertTrue(self.g.check().allowed)

    def test_negative_and_zero_cost_ignored(self):
        self.g.record(0.0, user="u1")
        self.g.record(-3.0, user="u1")
        self.assertEqual(self.g.spent(user="u1"), 0.0)


class ServiceIntegrationTests(unittest.TestCase):
    class _Gen:
        def answer(self, *a, **kw):
            class _A:
                text = "cevap [1]"
                citations = [{"n": 1, "chunk_id": "c1", "span_ids": ["s1"],
                              "pages": [1], "ders": "biyoloji"}]
                used_source_ids = ["c1"]
                invalid_citations = []
                abstained = False
                reason = ""
                cost_usd = 0.60
                cache_hit = False
            return _A()

    def _svc(self, **kw):
        from src.service.handler import RagService
        return RagService(self._Gen(), budget=BudgetGate(**kw))

    def test_chat_is_denied_after_the_ceiling(self):
        s = self._svc(user_daily_usd=1.0)
        self.assertFalse(s.chat({"query": "q", "user": "u1"})["abstained"])
        self.assertFalse(s.chat({"query": "q", "user": "u1"})["abstained"])
        ucuncu = s.chat({"query": "q", "user": "u1"})       # 1.20 > 1.00
        self.assertTrue(ucuncu["abstained"])
        self.assertEqual(ucuncu["reason"], "budget_exceeded")

    def test_denial_message_is_turkish_and_contract_shaped(self):
        s = self._svc(user_daily_usd=0.01)
        s.chat({"query": "q", "user": "u1"})
        out = s.chat({"query": "q", "user": "u1"})
        self.assertTrue(out["text"].strip())
        self.assertEqual(out["cost_usd"], 0.0)
        for alan in ("citations", "used_source_ids", "cache_hit"):
            self.assertIn(alan, out)

    def test_spend_is_recorded_only_after_a_real_answer(self):
        s = self._svc(user_daily_usd=10.0)
        s.chat({"query": "q", "user": "u1"})
        self.assertAlmostEqual(s.budget.spent(user="u1"), 0.60)


if __name__ == "__main__":
    unittest.main()
