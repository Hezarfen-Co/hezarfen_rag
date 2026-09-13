"""#M3-10 / #M4-4 (O-08, E-62, E-68) — LLM ARIZASI ÜRÜN YÜZEYİNDE.

ÖLÇÜLEN DURUM (EXP-009, gerçek koşum): DeepSeek çağrılarının **%92'si HTTP
429** döndü ve bir çağrı **300 s** sürdü. `urllib` zaman aşımı 120 s'ti —
öğrenci iki dakika boş ekrana bakıyordu. `runner._retry` yalnız 2 deneme
yapıyordu, backoff yoktu.

`tests/unit/test_llm_resilience.py` MEKANİZMAYI ölçüyor (retry sınıflaması,
backoff, devre kesici durum makinesi). BU DOSYA ÜRÜN YÜZEYİNİ ölçüyor:
sağlayıcı çöktüğünde ÖĞRENCİ NE GÖRÜYOR, backend ne alıyor, maliyet ne
oluyor. İkisi ayrı sorulardır: mekanizma doğru çalışıp yanıt yine de çıplak
500 olarak dönebilir.
"""
import unittest

from src.providers.resilience import CircuitBreaker, LlmUnavailable
from src.service import RagService
from src.service.handler import LLM_UNAVAILABLE_TEXT
from tests.unit.test_service import _ANS, _GenStub, _doc

# `_doc()` 12. sınıf / biyoloji üretir; özet ve soru uçları rol ister.
ROLE = {"role": "student", "sinif": "12", "ders_list": ["biyoloji"]}


class _FailingGen:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def answer(self, query, **kw):
        self.calls += 1
        raise self.error


class _FailingSummarizer:
    def __init__(self, error): self.error = error
    def summarize(self, units, **kw): raise self.error


class _FailingQuestionGen:
    def __init__(self, error): self.error = error
    def generate(self, units, **kw): raise self.error


class ChatPathTests(unittest.TestCase):
    def setUp(self):
        self.error = LlmUnavailable("429 rate limited", status=429)

    def test_response_is_contractual_not_a_raw_exception(self):
        """Backend her durumda AYNI alanları bekler (API-CONTRACT). İstisna
        yukarı sızarsa backend gövdeyi parse edemez ve öğrenciye teknik hata
        metni gider."""
        out = RagService(_FailingGen(self.error)).chat({"query": "fotosentez nedir"})
        for field in ("text", "abstained", "reason", "citations",
                      "used_source_ids", "cost_usd", "cache_hit"):
            self.assertIn(field, out, field)
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "llm_unavailable")

    def test_student_sees_turkish_non_technical_text(self):
        out = RagService(_FailingGen(self.error)).chat({"query": "s"})
        self.assertEqual(out["text"], LLM_UNAVAILABLE_TEXT)
        for leak in ("429", "Traceback", "LlmUnavailable", "rate limited",
                     "Exception"):
            self.assertNotIn(leak, out["text"], f"'{leak}' ogrenciye sizdi")

    def test_failure_is_not_billed(self):
        """Başarısız çağrı için para alınmaz; sayaç şişerse tavan haksız
        yere dolar ve öğrenci ertesi gün de kullanamaz."""
        svc = RagService(_FailingGen(self.error))
        out = svc.chat({"query": "s", "user": "ogr1"})
        self.assertEqual(out["cost_usd"], 0.0)
        self.assertEqual(svc.budget.spent(user="ogr1"), 0.0)

    def test_failure_invents_no_citations(self):
        out = RagService(_FailingGen(self.error)).chat({"query": "s"})
        self.assertEqual(out["citations"], [])
        self.assertEqual(out["used_source_ids"], [])

    def test_failure_is_not_reported_as_a_cache_hit(self):
        out = RagService(_FailingGen(self.error)).chat({"query": "s"})
        self.assertFalse(out["cache_hit"])

    def test_timeout_takes_the_same_path(self):
        out = RagService(_FailingGen(
            LlmUnavailable("timeout", status=None))).chat({"query": "s"})
        self.assertEqual(out["reason"], "llm_unavailable")

    def test_unexpected_exception_is_not_swallowed(self):
        """DÜRÜST SINIR: yalnız `LlmUnavailable` yakalanır. `KeyError` gibi
        bir PROGRAM HATASI sessizce 'llm_unavailable' diye raporlanırsa gerçek
        kusur gizlenir ve aylarca fark edilmez. Bu kasıtlı bir tercihtir;
        HTTP katmanı onu 503'e çevirir."""
        with self.assertRaises(KeyError):
            RagService(_FailingGen(KeyError("kod hatasi"))).chat({"query": "s"})


class SummaryAndQuestionPathTests(unittest.TestCase):
    """Arıza yalnız `chat`'i değil her ucu vurur."""

    def setUp(self):
        self.error = LlmUnavailable("503", status=503)

    def test_summary_failure_is_contractual(self):
        svc = RagService(_GenStub(_ANS), doc=_doc(),
                         summarizer=_FailingSummarizer(self.error), ders="biyoloji")
        out = svc.summarize({"scope": {"pages": [10]}, "role": ROLE})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "llm_unavailable")
        self.assertEqual(out["citations"], [])
        self.assertIn("scope_pages", out)

    def test_question_failure_is_contractual(self):
        svc = RagService(_GenStub(_ANS), doc=_doc(),
                         question_gen=_FailingQuestionGen(self.error), ders="biyoloji")
        out = svc.generate_questions({"scope": {"pages": [10]}, "role": ROLE})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "llm_unavailable")
        self.assertEqual(out["items"], [])

    def test_missing_role_is_a_different_reason_than_a_failure(self):
        """Yetki reddi ile sağlayıcı arızası aynı sebebi vermemeli; aksi hâlde
        olay incelemesi yanlış yöne gider."""
        svc = RagService(_GenStub(_ANS), doc=_doc(),
                         summarizer=_FailingSummarizer(self.error), ders="biyoloji")
        out = svc.summarize({"scope": {"pages": [10]}})
        self.assertEqual(out["reason"], "role_required")


class BreakerProductEffectTests(unittest.TestCase):
    """Sağlayıcı tamamen düştüğünde ürün BEKLEMEMELİ."""

    def test_open_breaker_never_calls_the_provider(self):
        """Kapanmış devrede her istek için 120 s beklemek, 30 öğrencilik
        sınıfta thread havuzunu tüketir ve SAĞLAM uçlar da (health, özet)
        cevap veremez hâle gelir."""
        cb = CircuitBreaker(threshold=2, cooldown_s=60.0)
        for _ in range(2):
            cb.record_failure()
        self.assertEqual(cb.state, "open")
        self.assertFalse(cb.allow())

    def test_half_open_allows_exactly_one_probe(self):
        clock_t = [0.0]
        cb = CircuitBreaker(threshold=1, cooldown_s=10.0, clock=lambda: clock_t[0])
        cb.record_failure()
        clock_t[0] = 11.0
        self.assertTrue(cb.allow(), "kurtarma denemesi hic yapilmiyor")
        self.assertFalse(cb.allow(), "yarim acikta sagligi coklu deneme sorguluyor")

    def test_success_closes_the_breaker(self):
        clock_t = [0.0]
        cb = CircuitBreaker(threshold=1, cooldown_s=10.0, clock=lambda: clock_t[0])
        cb.record_failure()
        clock_t[0] = 11.0
        cb.allow()
        cb.record_success()
        self.assertEqual(cb.state, "closed")
        self.assertTrue(cb.allow())

    def test_failure_while_half_open_reopens(self):
        """Yalnız sayaç artırılsaydı bozuk sağlayıcı HER istekte yeni bir
        deneme alırdı; devre kesici fiilen ölü olurdu."""
        clock_t = [0.0]
        cb = CircuitBreaker(threshold=1, cooldown_s=10.0, clock=lambda: clock_t[0])
        cb.record_failure()
        clock_t[0] = 11.0
        cb.allow()
        cb.record_failure()
        self.assertEqual(cb.state, "open", "bekleme sayaci sifirlanmadi")

    def test_state_is_exposed_for_readiness(self):
        cb = CircuitBreaker(threshold=1, cooldown_s=60.0)
        cb.record_failure()
        self.assertEqual(cb.snapshot()["state"], "open")


class PartialFailureTests(unittest.TestCase):
    """Bazı uçlar çalışırken bazıları çökebilir."""

    def test_summary_keeps_working_when_chat_is_down(self):
        from src.summarize.summarizer import GroundedSummary
        from tests.unit.test_service import _SumStub
        svc = RagService(_FailingGen(LlmUnavailable("429", status=429)),
                         doc=_doc(),
                         summarizer=_SumStub(GroundedSummary(
                             text="ozet [1].", citations=[], cost_usd=0.0)),
                         ders="biyoloji")
        self.assertTrue(svc.chat({"query": "s"})["abstained"])
        self.assertFalse(
            svc.summarize({"scope": {"pages": [10]}, "role": ROLE})["abstained"])

    def test_missing_component_has_its_own_reason(self):
        """'Bileşen kurulmadı' ile 'sağlayıcı çöktü' aynı şey değildir."""
        out = RagService(_GenStub(_ANS)).summarize({"scope": {"pages": [10]}})
        self.assertEqual(out["reason"], "summary_unavailable")


if __name__ == "__main__":
    unittest.main()
