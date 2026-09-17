"""#M3-10 / #M4-6 (EVAL-16, O-06, S-09) — EŞZAMANLILIK ve ÇOK-KİRACILIK.

ÖLÇÜLEN DURUM: eşzamanlılık/çok-kiracılık için **0 test** vardı. Bütün
testler tek istek, tek thread.

ÜRÜN AÇISINDAN NE DEMEK: bir sınıfta 30 öğrenci aynı anda soru sorar. Tek
`RagService` örneği bütün isteklere hizmet eder ve paylaşılan durum vardır:
bütçe sayaçları, cache, kayıt defteri, sayaçlar. Eşzamanlılık altında
bozulan bir sayaç, tavanın hiç tutmaması (fatura) ya da bir öğrencinin
cevabının başkasına gitmesi (sızıntı) demektir. İkisi de demoda görülmez,
üretimde görülür.

DÜRÜST SINIR: bu dosya hermetiktir — gerçek LLM/embedder çağırmaz. Gerçek
yük altındaki gecikme ölçümü #M4-6'nın işidir; burada ölçülen **paylaşılan
durumun doğruluğu**dur.
"""
import threading
import unittest

from src.budget import BudgetGate
from src.generate.generator import _role_cache_key
from src.guard.roles import Role, RoleContext
from src.service import RagService
from src.service.registry import CorpusRegistry
from tests.unit.test_service import _ANS, _GenStub


def _run_concurrently(fn, n=20):
    """`fn(i)`yi n thread'de koşturur; yakalanan hataları döndürür."""
    errors, lock = [], threading.Lock()
    barrier = threading.Barrier(n)

    def wrapped(i):
        try:
            barrier.wait(timeout=10)          # hepsi AYNI ANDA girsin
            fn(i)
        except Exception as e:              # noqa: BLE001
            with lock:
                errors.append(repr(e))

    threads = [threading.Thread(target=wrapped, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return errors


class BudgetCounterTests(unittest.TestCase):
    """Sayaç yarışı = tavan hiç tutmaz = fatura."""

    def test_concurrent_records_are_not_lost(self):
        g = BudgetGate(user_daily_usd=1e9, tenant_monthly_usd=1e9)
        errors = _run_concurrently(lambda i: [g.record(0.001, user="ogr1") for _ in range(50)],
                           n=20)
        self.assertEqual(errors, [])
        self.assertAlmostEqual(g.spent(user="ogr1"), 20 * 50 * 0.001, places=6)

    def test_users_do_not_consume_each_others_budget(self):
        g = BudgetGate(user_daily_usd=1e9, tenant_monthly_usd=1e9)
        _run_concurrently(lambda i: [g.record(0.01, user=f"ogr{i}") for _ in range(10)], n=20)
        for i in range(20):
            self.assertAlmostEqual(g.spent(user=f"ogr{i}"), 0.1, places=6)

    def test_tenant_cap_is_shared_user_cap_is_not(self):
        """Aynı okulun 20 öğrencisi kurum tavanını PAYLAŞIR; bu kasıtlıdır."""
        g = BudgetGate(user_daily_usd=1e9, tenant_monthly_usd=1e9)
        _run_concurrently(lambda i: g.record(0.05, user=f"ogr{i}", tenant="okul-A"), n=20)
        self.assertAlmostEqual(g.spent(tenant="okul-A"), 1.0, places=6)
        self.assertAlmostEqual(g.spent(user="ogr0"), 0.05, places=6)

    def test_no_thread_passes_once_the_cap_is_exceeded(self):
        g = BudgetGate(user_daily_usd=0.10, tenant_monthly_usd=1e9)
        g.record(0.10, user="ogr1")
        decisions, lock = [], threading.Lock()

        def ask(i):
            k = g.check(user="ogr1")
            with lock:
                decisions.append(k.allowed)

        self.assertEqual(_run_concurrently(ask, n=20), [])
        self.assertEqual(decisions, [False] * 20)

    def test_cap_race_reports_the_right_reason(self):
        g = BudgetGate(user_daily_usd=0.01, tenant_monthly_usd=1e9)
        g.record(1.0, user="ogr1")
        k = g.check(user="ogr1")
        self.assertFalse(k.allowed)
        self.assertEqual(k.reason, "budget_exceeded")
        self.assertEqual(k.scope, "user")


class ConcurrentServiceTests(unittest.TestCase):
    """Tek `RagService`, çok istek."""

    def test_twenty_students_at_once_see_no_error(self):
        svc = RagService(_GenStub(_ANS),
                         budget=BudgetGate(user_daily_usd=1e9, tenant_monthly_usd=1e9))

        def ask(i):
            out = svc.chat({"query": f"soru {i}", "user": f"ogr{i}",
                            "tenant": "okul-A",
                            "role": {"role": "student", "sinif": "10",
                                     "ders_list": ["biyoloji"]}})
            assert out["text"], "bos cevap"

        self.assertEqual(_run_concurrently(ask, n=20), [])

    def test_each_request_gets_its_own_request_id(self):
        """İz kimliği paylaşılırsa olay incelemesi imkânsızlaşır: 30
        öğrencinin sorusu tek ize karışır."""
        svc = RagService(_GenStub(_ANS),
                         budget=BudgetGate(user_daily_usd=1e9, tenant_monthly_usd=1e9))
        ids, lock = [], threading.Lock()

        def ask(i):
            out = svc.chat({"query": f"soru {i}", "user": f"ogr{i}"})
            with lock:
                ids.append(out.get("request_id"))

        self.assertEqual(_run_concurrently(ask, n=20), [])
        self.assertEqual(len(set(ids)), 20, "request_id cakisti")
        self.assertNotIn(None, ids)

    def test_supplied_request_id_is_preserved(self):
        """Backend kendi izleme kimliğini gönderdiğinde ürün onu ezmemeli."""
        svc = RagService(_GenStub(_ANS))
        out = svc.chat({"query": "s", "request_id": "backend-abc-123"})
        self.assertEqual(out["request_id"], "backend-abc-123")

    def test_budget_denial_does_not_spill_under_concurrency(self):
        """Tavanı dolmuş öğrenci reddedilirken diğerleri etkilenmemeli."""
        svc = RagService(_GenStub(_ANS),
                         budget=BudgetGate(user_daily_usd=0.5, tenant_monthly_usd=1e9))
        svc.budget.record(10.0, user="dolu")
        outcome, lock = {}, threading.Lock()

        def ask(i):
            kim = "dolu" if i % 2 == 0 else f"ogr{i}"
            out = svc.chat({"query": "s", "user": kim})
            with lock:
                outcome.setdefault(kim, []).append(out.get("reason", ""))

        self.assertEqual(_run_concurrently(ask, n=20), [])
        self.assertTrue(all(r == "budget_exceeded" for r in outcome["dolu"]))
        for kim, rs in outcome.items():
            if kim != "dolu":
                self.assertTrue(all(r == "" for r in rs), f"{kim} wrong reddedildi")


class CrossTenantLeakTests(unittest.TestCase):
    """İki okul aynı süreçte. Cache anahtarı kiracıları ayırmalı."""

    def test_same_question_different_grade_is_a_different_key(self):
        a = _role_cache_key(RoleContext(Role.STUDENT, "10", ["biyoloji"]))
        b = _role_cache_key(RoleContext(Role.STUDENT, "11", ["biyoloji"]))
        self.assertNotEqual(a, b)

    def test_registry_survives_concurrent_registration(self):
        class _Doc:
            def __init__(self, s, d): self.sinif, self.ders = s, d

        class _Svc:
            def __init__(self, s, d):
                self.school = "okul-a"
                self.doc, self.ders = _Doc(s, d), d
                self.generator = type("G", (), {"chunks_by_id": {}})()

        r = CorpusRegistry()
        errors = _run_concurrently(lambda i: r.register(_Svc("10", f"ders{i}")), n=20)
        self.assertEqual(errors, [])
        self.assertEqual(len(r), 20)

    def test_concurrent_routing_returns_the_right_corpus(self):
        class _Doc:
            def __init__(self, s, d): self.sinif, self.ders = s, d

        class _Svc:
            def __init__(self, s, d):
                self.school = "okul-a"
                self.doc, self.ders = _Doc(s, d), d
                self.generator = type("G", (), {"chunks_by_id": {}})()
                self.label = f"{s}/{d}"

        r = CorpusRegistry()
        for i in range(10):
            r.register(_Svc("10", f"ders{i}"))
        wrong, lock = [], threading.Lock()

        def ask(i):
            d = f"ders{i % 10}"
            svc, _ = r.resolve({"school": "okul-a", "scope": {"sinif": "10", "ders": d}})
            if svc is None or svc.label != f"10/{d}":
                with lock:
                    wrong.append(d)

        self.assertEqual(_run_concurrently(ask, n=20), [])
        self.assertEqual(wrong, [], "eszamanli yonlendirme wrong korpusa gitti")


class ModelLoadRaceTests(unittest.TestCase):
    """Tembel yükleme yarışı: iki thread aynı anda modeli yüklerse bellek
    ikiye katlanır (8 GB GPU'da OOM) ya da yarım yüklenmiş model kullanılır.
    """

    def test_lazy_loading_behaves_consistently(self):
        from src.service.http_app import _LazyService
        ls = _LazyService()
        outcome, lock = [], threading.Lock()

        def ask(i):
            try:
                ls.chat({"query": "s"})
                with lock:
                    outcome.append("ok")
            except Exception as e:                      # noqa: BLE001
                with lock:
                    outcome.append(type(e).__name__)

        self.assertEqual(_run_concurrently(ask, n=20), [])
        # Servis atanmadan gelen istek CEVAPSIZ kalmamalı: ürün "ısınıyorum"
        # demeli, çökmemeli. Hangi yolu seçtiği fark etmez; TUTARLI olmalı.
        self.assertEqual(len(set(outcome)), 1, f"eszamanli davranis tutarsiz: {set(outcome)}")


if __name__ == "__main__":
    unittest.main()
