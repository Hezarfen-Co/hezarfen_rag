"""#86 — çok-korpus servisi ÜRÜNE bağlandı.

ÖLÇÜLEN DURUM: `CorpusRegistry` yazıldı ve test edildi ama `http_app`'e HİÇ
BAĞLANMAMIŞTI. Servis tek `BOOK_PATH` okuyordu; diskte 15 kitap (lise 10, 15
ders) varken ürün yalnız birine cevap veriyordu.

ÜRÜN AÇISINDAN: okul demosunda öğrenci kimyaya geçtiği anda ürün "kaynaklarda
bulunamadı" der. Bu bir RAG hatası gibi görünür ama o korpus hiç yüklü
değildir — izleyen öğretmen için ürün "yalnız biyoloji biliyor" demektir.

Bu dosya üç şeyi sabitler:
  1. Yönlendirme doğru korpusa gider ve YETKİLENDİRME YERİNE GEÇMEZ.
  2. Tembel yükleme eşzamanlı isteklerde TEK kez çalışır (#80'in dersi).
  3. Bulunmayan korpus, sessiz bir RAG hatası değil TİPLİ bir red üretir.
"""
import threading
import unittest

from src.service.multi import MultiCorpusService, _parse, book_path, discover


class _Doc:
    def __init__(self, sinif, ders):
        self.sinif, self.ders = sinif, ders


class _FakeService:
    """`build_service` taklidi — gerçek model/indeks kurmadan yolu ölçer."""

    def __init__(self, sinif, ders):
        self.doc = _Doc(sinif, ders)
        self.ders = ders
        self.generator = type("G", (), {"chunks_by_id": {"c1": 1}})()
        self.calls = []

    def chat(self, req):
        self.calls.append(("chat", req))
        return {"text": f"{self.doc.sinif}/{self.ders}", "abstained": False,
                "reason": "", "citations": [], "used_source_ids": [],
                "cost_usd": 0.0, "cache_hit": False}

    def summarize(self, req):
        return {"text": self.ders, "abstained": False, "reason": "",
                "citations": [], "scope_pages": [], "hierarchical": False,
                "cost_usd": 0.0}

    def generate_questions(self, req):
        return {"items": [], "abstained": False, "reason": "",
                "span_ids": [], "pages": [], "cost_usd": 0.0}


def _svc(specs=("10/biyoloji", "10/kimya", "10/fizik"), gecikme=0.0,
         sayac=None):
    """Gerçek dosya sistemi ve modeller OLMADAN servis kurar."""
    def _builder(yol, *, sinif, ders, shared=None, **kw):
        if sayac is not None:
            sayac.append((sinif, ders))
        if gecikme:
            import time
            time.sleep(gecikme)
        return _FakeService(sinif, ders)

    s = MultiCorpusService(specs, shared=object(), builder=_builder)
    # Dosya varlığı kontrolünü aş: bu testler YOLU değil YÖNLENDİRMEYİ ölçüyor.
    s._specs = {k: __file__ for k in s._specs}
    return s


def _bekle(s, sinif, ders, timeout=5.0):
    """Arka plan korpus kurulumunun bitmesini bekler.

    Kurulum artık ASENKRON: ilk istek `service_warming_up` döner ve kurulum
    bir thread'de sürer (bkz. `ensure(block=False)` — soğuk ders 60 s'lik
    istek son tarihini aşıp HTTP 504 üretiyordu)."""
    import time
    son = time.time() + timeout
    while time.time() < son:
        if s.registry.get(str(sinif), str(ders)) is not None:
            return True
        if (str(sinif), str(ders)) in s._load_errors:
            return False
        time.sleep(0.01)
    return False


ROL_BIO = {"role": "student", "sinif": "10", "ders_list": ["biyoloji"]}
ROL_COK = {"role": "student", "sinif": "10",
           "ders_list": ["biyoloji", "kimya", "fizik"]}


class RoutingTests(unittest.TestCase):
    def test_scope_selects_the_corpus(self):
        s = _svc(); s.warm()
        out = s.chat({"query": "s", "scope": {"sinif": "10", "ders": "kimya"},
                      "role": ROL_COK})
        self.assertEqual(out["text"], "10/kimya")

    def test_single_subject_role_needs_no_scope(self):
        s = _svc(); s.warm()
        self.assertEqual(s.chat({"query": "s", "role": ROL_BIO})["text"],
                         "10/biyoloji")

    def test_options_ders_is_honoured(self):
        s = _svc(); s.warm()
        out = s.chat({"query": "s", "role": ROL_COK,
                      "options": {"ders": "fizik"}})
        self.assertEqual(out["text"], "10/fizik")

    def test_multi_subject_without_target_is_ambiguous_not_guessed(self):
        """Tahmin etmek YANLIŞ KİTAPTAN cevap üretmek demek olurdu."""
        s = _svc(); s.warm()
        out = s.chat({"query": "s", "role": ROL_COK})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "corpus_ambiguous")

    def test_unknown_corpus_is_a_typed_refusal(self):
        """Sessiz bir 'bulunamadı' RAG hatası gibi okunur; ayrı sebep şart."""
        s = _svc(); s.warm()
        out = s.chat({"query": "s",
                      "role": {"role": "student", "sinif": "10",
                               "ders_list": ["muzik"]}})
        self.assertEqual(out["reason"], "no_corpus")

    def test_refusal_text_is_turkish_and_actionable(self):
        s = _svc(); s.warm()
        for req, _ in (({"query": "s", "role": ROL_COK}, 0),
                       ({"query": "s", "role": {"sinif": "10",
                                                "ders_list": ["muzik"]}}, 0)):
            out = s.chat(req)
            with self.subTest(reason=out["reason"]):
                self.assertTrue(out["text"].strip())
                self.assertNotIn("corpus", out["text"].lower())

    def test_refusal_has_the_full_contract(self):
        """Backend her durumda AYNI alanları bekler (API-CONTRACT)."""
        _s = _svc(); _s.warm()
        out = _s.chat({"query": "s", "role": ROL_COK})
        for alan in ("text", "abstained", "reason", "citations",
                     "used_source_ids", "cost_usd", "cache_hit"):
            self.assertIn(alan, out, alan)

    def test_refusal_costs_nothing(self):
        _s = _svc(); _s.warm()
        self.assertEqual(_s.chat({"query": "s", "role": ROL_COK})["cost_usd"],
                         0.0)

    def test_summary_and_questions_route_too(self):
        s = _svc(); s.warm()
        self.assertEqual(
            s.summarize({"scope": {"sinif": "10", "ders": "kimya"},
                         "role": ROL_COK})["text"], "kimya")
        self.assertFalse(
            s.generate_questions({"scope": {"sinif": "10", "ders": "fizik"},
                                  "role": ROL_COK})["abstained"])

    def test_routing_is_not_authorization(self):
        """SINIR KAYDI: kapsam istemciden gelir ve yönlendirme onu İZLER.
        Yetki kararı alt servisin `can_access` kontrolündedir ve bu katman
        onu KALDIRMAZ. İkisini karıştırmak, rolün istediği dersi seçmesine
        izin vermek olurdu (SEC-01)."""
        s = _svc(); s.warm()
        out = s.chat({"query": "s", "scope": {"sinif": "10", "ders": "fizik"},
                      "role": ROL_BIO})
        self.assertEqual(out["text"], "10/fizik", "yonlendirme kapsami izlemeli")
        from src.guard.roles import Role, RoleContext, can_access
        ctx = RoleContext(role=Role.STUDENT, sinif="10", ders_list=["biyoloji"])
        self.assertFalse(can_access(ctx, sinif="10", ders="fizik"),
                         "yetki katmani bu erisimi REDDETMELI")


class LazyLoadingTests(unittest.TestCase):
    def test_nothing_is_built_until_asked(self):
        """15 kitabı açılışta kurmak ~12 dakikalık sağır servis demekti
        (tek kitap GPU'da 47,6 s) ve indeks kalıcı olmadığı için (#75) bu
        bedel HER yeniden başlatmada ödenirdi."""
        sayac = []
        s = _svc(sayac=sayac)
        self.assertEqual(sayac, [])
        self.assertEqual(s.loaded(), [])

    def test_cold_subject_answers_immediately_with_warming(self):
        """KOŞULARAK BULUNDU: soğuk dersin ilk sorusu korpus kurulurken
        (GPU ~48 s, CPU ~550 s) 60 s'lik istek son tarihini aşıyor ve istemci
        **HTTP 504** alıyordu. Öğrenci kimyaya geçince zaman aşımı görüyordu.
        Artık hemen tipli bir "hazırlanıyor" cevabı döner."""
        s = _svc(gecikme=0.2)
        out = s.chat({"query": "s", "role": ROL_BIO})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "service_warming_up")
        self.assertTrue(out["text"].strip())

    def test_only_the_asked_corpus_is_built(self):
        sayac, kilit = [], threading.Lock()

        def _builder(yol, *, sinif, ders, shared=None, **kw):
            with kilit:
                sayac.append((sinif, ders))
            return _FakeService(sinif, ders)

        s = _svc()
        s._build = _builder
        s.chat({"query": "s", "role": ROL_BIO})
        _bekle(s, "10", "biyoloji")
        self.assertEqual(sayac, [("10", "biyoloji")])

    def test_second_request_reuses_the_built_corpus(self):
        sayac, kilit = [], threading.Lock()

        def _builder(yol, *, sinif, ders, shared=None, **kw):
            with kilit:
                sayac.append((sinif, ders))
            return _FakeService(sinif, ders)

        s = _svc()
        s._build = _builder
        s.chat({"query": "s", "role": ROL_BIO})
        self.assertTrue(_bekle(s, "10", "biyoloji"))
        for _ in range(5):
            out = s.chat({"query": "s", "role": ROL_BIO})
        self.assertEqual(len(sayac), 1)
        self.assertFalse(out["abstained"], "kurulu korpus hala bekletiyor")

    def test_concurrent_first_requests_build_once(self):
        """#80'in dersi: kilitsiz tembel yükleme, 8 eşzamanlı istekte 8
        paralel indeks kurulumu demekti (gerçek sınıfla ölçülmüştü)."""
        sayac, kilit = [], threading.Lock()
        guvenli = []

        def _say(x):
            with kilit:
                guvenli.append(x)

        s = _svc(gecikme=0.05, sayac=None)
        orj = s._build

        def _builder(yol, *, sinif, ders, shared=None, **kw):
            _say((sinif, ders))
            return orj(yol, sinif=sinif, ders=ders, shared=shared, **kw)

        s._build = _builder
        bariyer = threading.Barrier(8)

        def sor():
            bariyer.wait(timeout=10)
            s.chat({"query": "s", "role": ROL_BIO})

        ths = [threading.Thread(target=sor) for _ in range(8)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(timeout=30)
        _bekle(s, "10", "biyoloji")
        self.assertEqual(len(guvenli), 1, f"korpus {len(guvenli)} kez kuruldu")

    def test_warm_builds_everything_upfront(self):
        sayac = []
        s = _svc(sayac=sayac)
        sonuc = s.warm()
        self.assertEqual(len(sayac), 3)
        self.assertTrue(all(sonuc.values()))

    def test_a_broken_corpus_is_not_retried_forever(self):
        """Bozuk bir kitabı her istekte yeniden kurmaya çalışmak, o ders
        sorulduğunda servisi kilitlerdi."""
        deneme = []

        def _patlar(yol, *, sinif, ders, shared=None, **kw):
            deneme.append((sinif, ders))
            raise RuntimeError("bozuk pdf")

        s = MultiCorpusService(["10/biyoloji"], shared=object(),
                               builder=_patlar)
        s._specs = {k: __file__ for k in s._specs}
        s.chat({"query": "s", "role": ROL_BIO})
        _bekle(s, "10", "biyoloji")
        for _ in range(4):
            out = s.chat({"query": "s", "role": ROL_BIO})
        self.assertEqual(len(deneme), 1, "bozuk korpus tekrar tekrar deneniyor")
        self.assertEqual(out["reason"], "no_corpus")

    def test_missing_file_is_not_an_exception(self):
        """Yapılandırmada yazan ama diskte olmayan kitap, çökme değil red."""
        s = MultiCorpusService(["10/olmayan-ders"], shared=object(),
                               builder=lambda *a, **k: _FakeService("10", "x"))
        out = s.chat({"query": "s",
                      "role": {"role": "student", "sinif": "10",
                               "ders_list": ["olmayan-ders"]}})
        self.assertEqual(out["reason"], "no_corpus")
        self.assertEqual(s.building(), [], "var olmayan dosya icin thread acildi")

    def test_status_is_json_serialisable(self):
        """`/ready` bu sözlüğü JSON'a çevirir; tuple anahtar 500 üretirdi."""
        import json
        def _patlar(*a, **k):
            raise RuntimeError("bozuk")
        s = MultiCorpusService(["10/biyoloji"], shared=object(), builder=_patlar)
        s._specs = {k: __file__ for k in s._specs}
        s.chat({"query": "s", "role": ROL_BIO})
        _bekle(s, "10", "biyoloji")
        json.dumps(s.status())


class StatusTests(unittest.TestCase):
    def test_status_separates_known_from_loaded(self):
        """Operatör "hangi ders hazır" sorusunu tahminle değil uçtan
        cevaplayabilmeli; ilk soru yavaş olacak dersler görünür olmalı."""
        s = _svc()
        d = s.status()
        self.assertEqual(len(d["bilinen"]), 3)
        self.assertEqual(d["yuklu"], [])
        s.chat({"query": "s", "role": ROL_BIO})
        _bekle(s, "10", "biyoloji")
        self.assertEqual(s.status()["yuklu"], ["10/biyoloji"])

    def test_load_errors_are_surfaced(self):
        def _patlar(*a, **k):
            raise RuntimeError("bozuk")
        s = MultiCorpusService(["10/biyoloji"], shared=object(), builder=_patlar)
        s._specs = {k: __file__ for k in s._specs}
        s.chat({"query": "s", "role": ROL_BIO})
        _bekle(s, "10", "biyoloji")
        self.assertIn("10/biyoloji", s.status()["hatalar"])

    def test_corpus_limit_is_a_deliberate_valve(self):
        """#75 çözülene kadar RSS korpus sayısıyla lineer büyür; sessizce
        belleği tüketmektense açıkça reddetmek yeğdir."""
        s = _svc()
        s.registry.max_corpora = 1
        s.chat({"query": "s", "role": ROL_BIO})
        _bekle(s, "10", "biyoloji")
        s.chat({"query": "s", "options": {"ders": "kimya"}, "role": ROL_COK})
        _bekle(s, "10", "kimya")
        out = s.chat({"query": "s", "options": {"ders": "kimya"},
                      "role": ROL_COK})
        self.assertEqual(out["reason"], "no_corpus",
                         "sinir asilinca istisna sizdi (500) ya da sessizce gecti")
        self.assertIn("limit", str(s.status()["hatalar"]))


class DiscoveryTests(unittest.TestCase):
    def test_discover_finds_real_books(self):
        bulunan = discover()
        if not bulunan:
            self.skipTest("bu makinede korpus yok")
        self.assertTrue(all(len(x) == 2 for x in bulunan))
        self.assertEqual(bulunan, sorted(bulunan), "sira deterministik olmali")

    def test_book_path_shape(self):
        self.assertTrue(book_path("10", "kimya").endswith(
            "10/kimya/kitap.pdf"))

    def test_bad_spec_is_refused(self):
        for bozuk in ("bozuk", "", "10/", "/biyoloji", "a/b/c"):
            with self.subTest(bozuk=bozuk):
                with self.assertRaises(ValueError):
                    _parse(bozuk)


if __name__ == "__main__":
    unittest.main()


class SharedModelsTests(unittest.TestCase):
    """Paylaşımlı model havuzu (#86).

    KOŞARAK BULUNDU, TESTLERDEN KAÇTI: sağlayıcı fonksiyonları
    (`build_embedder`/`build_reranker`) `build_service`'in İÇİNE import
    edilmişti, ama `SharedModels` modül seviyesinde bir sınıf ve onları
    göremiyordu → çalışma anında `NameError: name 'build_embedder' is not
    defined`. Bütün birim testleri geçiyordu çünkü hiçbiri `SharedModels`'ı
    GERÇEKTEN kurmuyordu; hata yalnız canlı serviste, korpus kurulurken
    ortaya çıktı ve loglara `[korpus][HATA]` olarak düştü.
    """

    def test_shared_models_resolve_their_dependencies(self):
        from src.service.http_app import SharedModels
        sm = SharedModels()
        from src.embed.embedder import BGEM3Embedder
        self.assertIsInstance(sm.embedder, BGEM3Embedder)

    def test_embedder_is_built_once(self):
        """15 kitap × 2,3 GB model = 8 GB GPU'da OOM. Model korpustan
        BAĞIMSIZDIR; indeks değildir."""
        from src.service.http_app import SharedModels
        sm = SharedModels()
        self.assertIs(sm.embedder, sm.embedder)

    def test_provider_symbols_are_module_level(self):
        """Sembollerin `build_service` içine geri taşınması aynı NameError'ı
        geri getirir; test bunu kilitliyor."""
        import src.service.http_app as m
        for ad in ("build_embedder", "build_reranker",
                   "check_abstain_compatibility"):
            self.assertTrue(hasattr(m, ad), f"{ad} modul seviyesinde degil")


class SerialBuildTests(unittest.TestCase):
    """Korpus kurulumları SERİ olmalı.

    KOŞARAK BULUNDU: iki korpus aynı anda kurulunca süreç **SEGFAULT** ile
    çöktü. Sebep, paylaşılan BGE-M3 örneğini iki thread'den eş zamanlı
    `encode()` etmek (FlagEmbedding/torch bu kullanımda güvenli değil) ve
    iki indeks kurulumunun VRAM tepesini ikiye katlaması (8 GB kart).

    Demoda bu şöyle görünürdü: öğrenci biyolojiyi sorar, hemen kimyaya
    geçer, servis çöker.
    """

    def test_builds_never_overlap(self):
        import time
        ayni_anda, en_fazla, kilit = [0], [0], threading.Lock()

        def _builder(yol, *, sinif, ders, shared=None, **kw):
            with kilit:
                ayni_anda[0] += 1
                en_fazla[0] = max(en_fazla[0], ayni_anda[0])
            time.sleep(0.05)
            with kilit:
                ayni_anda[0] -= 1
            return _FakeService(sinif, ders)

        s = _svc()
        s._build = _builder
        for ders in ("biyoloji", "kimya", "fizik"):
            s.chat({"query": "s", "options": {"ders": ders}, "role": ROL_COK})
        for ders in ("biyoloji", "kimya", "fizik"):
            _bekle(s, "10", ders, timeout=10)
        self.assertEqual(en_fazla[0], 1,
                         f"{en_fazla[0]} korpus AYNI ANDA kuruldu (segfault riski)")
        self.assertEqual(len(s.loaded()), 3)

    def test_queries_are_not_blocked_by_a_build(self):
        """Kurulum kilidi SORGULARI bekletmemeli: kurulu bir ders, başka bir
        ders kurulurken de cevap verebilmeli."""
        import time
        s = _svc()
        s.warm([("10", "biyoloji")])

        def _yavas(yol, *, sinif, ders, shared=None, **kw):
            time.sleep(0.3)
            return _FakeService(sinif, ders)

        s._build = _yavas
        s.chat({"query": "s", "options": {"ders": "kimya"}, "role": ROL_COK})
        t0 = time.perf_counter()
        out = s.chat({"query": "s", "options": {"ders": "biyoloji"},
                      "role": ROL_COK})
        gecen = time.perf_counter() - t0
        self.assertFalse(out["abstained"])
        self.assertLess(gecen, 0.2, "kurulum kilidi sorguyu bekletti")


class SharedModelsDeadlockTests(unittest.TestCase):
    """KOŞARAK BULUNDU: `SharedModels` iç kilidi DEADLOCK üretiyordu.

    `reranker` özelliği kilidi tutarken uyarı üretmek için `self.embedder`'a
    bakıyor, o da AYNI kilidi istiyordu. Düz `Lock` reentrant değildir →
    korpus kurulum thread'i sessizce sonsuza kadar bekliyordu.

    BELİRTİ YANILTICIYDI: `/ready` sürekli `kuruluyor` diyordu, hiçbir hata
    log'u düşmüyordu, 900 saniyede tek korpus bile hazır olmadı. "Çok yavaş"
    gibi görünen şey aslında "hiç ilerlemiyor"du.
    """

    def test_reranker_after_embedder_does_not_deadlock(self):
        import threading

        from src.service.http_app import SharedModels
        sm = SharedModels()
        sm._embedder = object()          # gomme kurulmus gibi davran
        sm._reranker = object()          # agir model YUKLENMESIN

        bitti = threading.Event()

        def _dokun():
            _ = sm.reranker
            _ = sm.embedder
            bitti.set()

        t = threading.Thread(target=_dokun, daemon=True)
        t.start()
        self.assertTrue(bitti.wait(timeout=5),
                        "SharedModels kilidi deadlock uretti")

    def test_lock_is_reentrant(self):
        from src.service.http_app import SharedModels
        sm = SharedModels()
        with sm._lock:
            with sm._lock:               # duz Lock burada kilitlenirdi
                pass
