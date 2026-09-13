"""#78 (EXP-010/OPS-06) — LLM hata yolları: retry + backoff + devre kesici.

ÖLÇÜLEN DURUM: `providers/deepseek.py` tek `urlopen` ile çağırıyordu,
retry/backoff YOK, `timeout=120.0`. `RagService.chat` istisnayı yakalamıyordu;
stub 429 ile ölçüldü → **HTTP 500, gövde "Internal Server Error"** (reason yok,
request_id yok). Backend ise `abstained/reason` sözleşmesine göre yazılmış ve
bu gövdeyi **parse edemiyor**.

Gerçek hayat kanıtı (EXP-009): DeepSeek/NVIDIA uçlarında **%92 HTTP 429** ve
300 s timeout yaşandı.
"""
import unittest
import urllib.error

from src.providers.deepseek import DEFAULT_TIMEOUT, _is_retryable
from src.providers.resilience import (BREAKER_THRESHOLD, CircuitBreaker,
                                      LlmUnavailable, backoff_delay,
                                      call_with_retry)


def _http(code):
    return urllib.error.HTTPError("u", code, "m", {}, None)


class RetryClassificationTests(unittest.TestCase):
    def test_transient_statuses_are_retried(self):
        for kod in (408, 429, 500, 502, 503, 504):
            with self.subTest(kod):
                self.assertTrue(_is_retryable(_http(kod))[0])

    def test_client_errors_are_not_retried(self):
        """Tekrar denemek yalnız kota yakar ve gecikme ekler — istek yanlış."""
        for kod in (400, 401, 403, 404, 422):
            with self.subTest(kod):
                self.assertFalse(_is_retryable(_http(kod))[0])

    def test_network_errors_are_retried(self):
        for exc in (urllib.error.URLError("kapali"), TimeoutError(),
                    ConnectionResetError()):
            with self.subTest(type(exc).__name__):
                self.assertTrue(_is_retryable(exc)[0])

    def test_unknown_exception_is_not_retried(self):
        self.assertFalse(_is_retryable(ValueError("bozuk json"))[0])


class BackoffTests(unittest.TestCase):
    def test_exponential_with_cap(self):
        v = [backoff_delay(i, rng=lambda: 1.0) for i in range(1, 7)]
        self.assertEqual(v[:5], [0.5, 1.0, 2.0, 4.0, 8.0])
        self.assertEqual(v[5], 8.0)              # tavan

    def test_jitter_is_between_half_and_full(self):
        """JITTER ŞART: sağlayıcı 429 verdiğinde bütün istemciler aynı anda
        tekrar denerse yük dalgası aynen tekrarlanır — EXP-009'daki %92 429
        tam olarak böyle oluştu."""
        tam = backoff_delay(3, rng=lambda: 1.0)
        yari = backoff_delay(3, rng=lambda: 0.0)
        self.assertAlmostEqual(tam, 2.0)
        self.assertAlmostEqual(yari, 1.0)


class RetryLoopTests(unittest.TestCase):
    def setUp(self):
        self.uyku = []

    def _sleep(self, s):
        self.uyku.append(s)

    def test_succeeds_after_transient_failures(self):
        deneme = {"n": 0}

        def fn():
            deneme["n"] += 1
            if deneme["n"] < 3:
                raise _http(429)
            return "ok"

        out = call_with_retry(fn, is_retryable=_is_retryable, max_attempts=3,
                              sleep=self._sleep, rng=lambda: 1.0)
        self.assertEqual(out, "ok")
        self.assertEqual(deneme["n"], 3)
        self.assertEqual(len(self.uyku), 2)

    def test_non_retryable_fails_immediately(self):
        deneme = {"n": 0}

        def fn():
            deneme["n"] += 1
            raise _http(401)

        with self.assertRaises(LlmUnavailable):
            call_with_retry(fn, is_retryable=_is_retryable, max_attempts=5,
                            sleep=self._sleep)
        self.assertEqual(deneme["n"], 1)
        self.assertEqual(self.uyku, [])

    def test_budget_stops_waiting(self):
        """"3 deneme × 30 s + bekleme" kullanıcıyı dakikalarca bekletirdi.

        DİKKAT — ilk yazımda aritmetiği yanlış kurmuştum: saat çağrı başına
        20 s ilerliyor, ilk hatadan sonra geçen 20 s ve bekleme 0,5 s;
        20,5 < 30 olduğu için **beklemek doğru davranış**. Bütçe ancak ikinci
        hatadan sonra (geçen 40 s) devreye giriyor. Test artık bunu ölçüyor."""
        saat = {"t": 0.0}

        def clock():
            saat["t"] += 20.0
            return saat["t"]

        with self.assertRaises(LlmUnavailable):
            call_with_retry(lambda: (_ for _ in ()).throw(_http(503)),
                            is_retryable=_is_retryable, max_attempts=5,
                            budget_s=30.0, sleep=self._sleep, clock=clock,
                            rng=lambda: 1.0)
        self.assertEqual(len(self.uyku), 1, "bütçe aşıldığı hâlde beklendi")
        self.assertLess(sum(self.uyku), 30.0)

    def test_budget_zero_never_waits(self):
        with self.assertRaises(LlmUnavailable):
            call_with_retry(lambda: (_ for _ in ()).throw(_http(503)),
                            is_retryable=_is_retryable, max_attempts=5,
                            budget_s=0.0, sleep=self._sleep, rng=lambda: 1.0)
        self.assertEqual(self.uyku, [])

    def test_error_is_typed_and_carries_status(self):
        with self.assertRaises(LlmUnavailable) as ctx:
            call_with_retry(lambda: (_ for _ in ()).throw(_http(429)),
                            is_retryable=_is_retryable, max_attempts=2,
                            sleep=self._sleep, rng=lambda: 1.0)
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(ctx.exception.attempts, 2)


class CircuitBreakerTests(unittest.TestCase):
    """Sağlayıcı 10 dk bozuksa, kesici olmadan HER istek tam `timeout` kadar bir
    thread tutar; anyio havuzu (40) dolar ve **`/health` bile yanıt veremez**."""

    def setUp(self):
        self.t = [0.0]
        self.b = CircuitBreaker(threshold=2, cooldown_s=10,
                                clock=lambda: self.t[0])

    def test_opens_after_threshold(self):
        self.assertEqual(self.b.state, "closed")
        self.b.record_failure()
        self.assertEqual(self.b.state, "closed")
        self.b.record_failure()
        self.assertEqual(self.b.state, "open")
        self.assertFalse(self.b.allow())

    def test_open_breaker_fails_fast(self):
        self.b.record_failure(); self.b.record_failure()
        cagri = {"n": 0}

        def fn():
            cagri["n"] += 1
            return "ok"

        with self.assertRaises(LlmUnavailable):
            call_with_retry(fn, is_retryable=_is_retryable, breaker=self.b)
        self.assertEqual(cagri["n"], 0, "kesici açıkken sağlayıcı çağrıldı")

    def test_half_open_allows_exactly_one_probe(self):
        self.b.record_failure(); self.b.record_failure()
        self.t[0] = 11
        self.assertEqual(self.b.state, "half_open")
        self.assertTrue(self.b.allow())
        self.assertFalse(self.b.allow(), "ikinci deneme de geçti")

    def test_success_closes_the_breaker(self):
        self.b.record_failure(); self.b.record_failure()
        self.t[0] = 11
        self.b.allow()
        self.b.record_success()
        self.assertEqual(self.b.state, "closed")
        self.assertTrue(self.b.allow())

    def test_failure_in_half_open_reopens(self):
        self.b.record_failure(); self.b.record_failure()
        self.t[0] = 11
        self.b.allow()
        self.b.record_failure()
        self.assertEqual(self.b.state, "open")

    def test_snapshot_exposes_state_for_readiness(self):
        s = self.b.snapshot()
        self.assertEqual(s["state"], "closed")
        self.assertIn("threshold", s)


class TimeoutDefaultTests(unittest.TestCase):
    def test_default_timeout_is_not_120(self):
        """Ölçülen LLM p50'leri 1,94–10,44 s; 120 s'lik tavan öğrenciyi iki
        dakika bekletip sonunda hata göstermek demekti."""
        self.assertLessEqual(DEFAULT_TIMEOUT, 60.0)
        self.assertGreaterEqual(DEFAULT_TIMEOUT, 10.0)

    def test_breaker_threshold_is_sane(self):
        self.assertGreaterEqual(BREAKER_THRESHOLD, 2)


class ServiceContractTests(unittest.TestCase):
    """Denetimin asıl bulgusu: LLM arızası HTTP 500 + "Internal Server Error"
    olarak dönüyordu; backend bunu parse edemiyor."""

    class _PatlayanGenerator:
        def answer(self, *a, **kw):
            raise LlmUnavailable("saglayici yok", status=429, attempts=3)

    def _service(self):
        from src.service.handler import RagService
        return RagService(self._PatlayanGenerator())

    def test_chat_returns_typed_refusal_not_an_exception(self):
        out = self._service().chat({"query": "DNA nedir?"})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "llm_unavailable")
        self.assertEqual(out["citations"], [])
        self.assertEqual(out["cost_usd"], 0.0)

    def test_user_message_is_turkish_and_actionable(self):
        metin = self._service().chat({"query": "q"})["text"]
        self.assertTrue(metin.strip())
        self.assertNotIn("Internal Server Error", metin)
        self.assertIn("tekrar", metin.lower())

    def test_contract_fields_are_all_present(self):
        out = self._service().chat({"query": "q"})
        for alan in ("text", "abstained", "reason", "citations",
                     "used_source_ids", "cost_usd", "cache_hit"):
            self.assertIn(alan, out, alan)


if __name__ == "__main__":
    unittest.main()
