"""#86 (EXP-010/OPS-08+09) — çok-korpus yönlendirme.

ÖLÇÜLEN DURUM: süreç = **1 kitap = 1 ders**. Kaynak kataloğu, yönlendirme,
indeks kataloğu yoktu.

ÜRÜN AÇISINDAN: öğrencinin 19 dersi var; servis yalnız birini cevaplayabiliyor.
Demoda öğrenci fiziğe geçince ürün "kaynaklarda bulunamadı" diyor — bu bir RAG
hatası gibi görünüyor ama aslında **yanlış korpusa soruluyor**.

KRİTİK AYRIM: yönlendirme **yetkilendirme değildir**. Burada yalnız "hangi
kitap" sorusu cevaplanır; "bu öğrenci onu görebilir mi" sorusunu
`guard/roles.can_access` cevaplar. İkisini karıştırmak, rolün istediği dersi
seçmesine izin vermek olurdu — SEC-01'in tam olarak bu şekli ölçülmüştü.
"""
import unittest

from src.service.registry import CorpusKey, CorpusRegistry


class _Doc:
    def __init__(self, sinif, ders):
        self.sinif = sinif
        self.ders = ders


class _Gen:
    def __init__(self, n=0):
        self.chunks_by_id = {f"c{i}": i for i in range(n)}


class _Svc:
    def __init__(self, sinif, ders, n=0):
        self.doc = _Doc(sinif, ders)
        self.ders = ders
        self.generator = _Gen(n)


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.r = CorpusRegistry()

    def test_register_reads_scope_from_the_service(self):
        k = self.r.register(_Svc("10", "biyoloji"))
        self.assertEqual(k, CorpusKey("10", "biyoloji"))
        self.assertEqual(len(self.r), 1)

    def test_explicit_scope_wins(self):
        k = self.r.register(_Svc("10", "biyoloji"), sinif="11", ders="fizik")
        self.assertEqual(str(k), "11/fizik")

    def test_scopeless_service_is_refused(self):
        """Sınıf/ders bilinmeden kayıt, sessizce yanlış yönlendirme demektir."""
        class _Bos:
            doc = None
            ders = ""
        with self.assertRaises(ValueError):
            self.r.register(_Bos())

    def test_re_register_replaces(self):
        self.r.register(_Svc("10", "biyoloji", n=5))
        self.r.register(_Svc("10", "biyoloji", n=9))
        self.assertEqual(len(self.r), 1)
        self.assertEqual(self.r.stats().chunks, 9)

    def test_unregister(self):
        self.r.register(_Svc("10", "biyoloji"))
        self.assertTrue(self.r.unregister("10", "biyoloji"))
        self.assertFalse(self.r.unregister("10", "biyoloji"))
        self.assertEqual(len(self.r), 0)

    def test_corpus_limit_is_a_deliberate_valve(self):
        """Ölçek duvarı ölçüldü (#75 yokken RSS lineer büyüyor): sessizce
        belleği tüketmektense açıkça reddetmek yeğdir."""
        r = CorpusRegistry(max_corpora=2)
        r.register(_Svc("10", "biyoloji"))
        r.register(_Svc("10", "fizik"))
        with self.assertRaises(ValueError):
            r.register(_Svc("10", "kimya"))

    def test_limit_does_not_block_replacing_an_existing_corpus(self):
        r = CorpusRegistry(max_corpora=1)
        r.register(_Svc("10", "biyoloji", n=1))
        r.register(_Svc("10", "biyoloji", n=2))      # aynı anahtar → yer açmaz
        self.assertEqual(r.stats().chunks, 2)


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.r = CorpusRegistry()
        self.bio = _Svc("10", "biyoloji", n=3)
        self.fiz = _Svc("10", "fizik", n=4)
        self.r.register(self.bio)
        self.r.register(self.fiz)

    def test_scope_selects_the_corpus(self):
        svc, _ = self.r.resolve({"scope": {"sinif": "10", "ders": "fizik"}})
        self.assertIs(svc, self.fiz)

    def test_single_subject_role_is_unambiguous(self):
        svc, _ = self.r.resolve(
            {"role": {"role": "student", "sinif": "10", "ders_list": ["biyoloji"]}})
        self.assertIs(svc, self.bio)

    def test_options_ders_is_honoured(self):
        svc, _ = self.r.resolve(
            {"role": {"sinif": "10", "ders_list": ["biyoloji", "fizik"]},
             "options": {"ders": "fizik"}})
        self.assertIs(svc, self.fiz)

    def test_multi_subject_role_without_a_target_is_ambiguous(self):
        """Tahmin etmek yanlış kitaptan cevap üretmek demek olurdu."""
        svc, sebep = self.r.resolve(
            {"role": {"sinif": "10", "ders_list": ["biyoloji", "fizik"]}})
        self.assertIsNone(svc)
        self.assertEqual(sebep, "corpus_ambiguous")

    def test_multi_subject_role_resolves_when_only_one_is_loaded(self):
        """Öğrencinin 19 dersi olabilir ama süreçte tek korpus yüklüyse
        belirsizlik yoktur."""
        r = CorpusRegistry()
        r.register(self.bio)
        svc, _ = r.resolve({"role": {"sinif": "10",
                                     "ders_list": ["biyoloji", "fizik", "kimya"]}})
        self.assertIs(svc, self.bio)

    def test_unknown_corpus_is_reported_not_guessed(self):
        svc, sebep = self.r.resolve({"scope": {"sinif": "12", "ders": "biyoloji"}})
        self.assertIsNone(svc)
        self.assertEqual(sebep, "no_corpus")

    def test_missing_scope_is_not_a_crash(self):
        for istek in ({}, {"role": {}}, {"scope": {}},
                      {"role": {"sinif": "10"}}):
            with self.subTest(istek=sorted(istek)):
                svc, sebep = self.r.resolve(istek)
                self.assertIsNone(svc)
                self.assertTrue(sebep)

    def test_routing_is_not_authorization(self):
        """Kapsam istemciden gelir; yönlendirme onu KABUL EDER ama yetki
        kararı ayrıdır. Bu test sınırı kayda geçirir: kayıt defteri rol
        kontrolü YAPMAZ, servis yapar (SEC-01)."""
        svc, _ = self.r.resolve({"scope": {"sinif": "10", "ders": "fizik"},
                                 "role": {"role": "student", "sinif": "10",
                                          "ders_list": ["biyoloji"]}})
        self.assertIs(svc, self.fiz, "yönlendirme kapsamı izlemeli")
        from src.guard.roles import Role, RoleContext, can_access
        ctx = RoleContext(role=Role.STUDENT, sinif="10", ders_list=["biyoloji"])
        self.assertFalse(can_access(ctx, sinif="10", ders="fizik"),
                         "yetki katmanı bu erişimi REDDETMELİ")


class StatsTests(unittest.TestCase):
    def test_stats_report_scale(self):
        r = CorpusRegistry()
        r.register(_Svc("10", "biyoloji", n=100))
        r.register(_Svc("10", "fizik", n=250))
        s = r.stats()
        self.assertEqual(s.corpora, 2)
        self.assertEqual(s.chunks, 350)
        self.assertEqual(s.detail["10/fizik"], 250)

    def test_keys_are_sorted_and_stable(self):
        r = CorpusRegistry()
        for d in ("fizik", "biyoloji", "kimya"):
            r.register(_Svc("10", d))
        self.assertEqual([str(k) for k in r.keys()],
                         ["10/biyoloji", "10/fizik", "10/kimya"])


class ThreadSafetyTests(unittest.TestCase):
    def test_concurrent_registration(self):
        import threading
        r = CorpusRegistry()
        hatalar = []

        def kaydet(i):
            try:
                r.register(_Svc("10", f"ders{i}"))
            except Exception as e:                  # noqa: BLE001
                hatalar.append(repr(e))

        ths = [threading.Thread(target=kaydet, args=(i,)) for i in range(20)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(hatalar, [])
        self.assertEqual(len(r), 20)


if __name__ == "__main__":
    unittest.main()
