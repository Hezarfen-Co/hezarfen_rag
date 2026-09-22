"""#2 RagService (transport-bağımsız handler) testleri — hermetik (stub bileşen)."""
import unittest

from src.service import RagService
from src.generate.generator import GroundedAnswer
from src.summarize.summarizer import GroundedSummary
from src.generate.question_gen import GeneratedQuestionSet, GeneratedQuestion
from src.ingest.canonical import CanonicalDoc, CanonicalUnit
from src.guard.roles import Role


class _GenStub:
    """Generator taklidi.

    `**kw` ŞART: bu stub gerçek imzadan geri kaldığında test, ürün kodundaki
    yeni bir parametreyi (örn. #85'te eklenen `trace=`) `TypeError` ile
    yakalamak yerine kırılıyor. Stub'ın esnek olması, testin ölçmek istediği
    şeyi (rol eşlemesi) ölçmeye devam etmesini sağlar; gerçek imza uyumu
    entegrasyon/e2e testlerinin işidir."""

    def __init__(self, ans):
        self.ans = ans
        self.last_role = "UNSET"
        self.last_trace = None

    def answer(self, query, *, history=None, top_n=6, candidate_n=40,
               role_ctx="UNSET", trace=None, **kw):
        self.last_role = role_ctx
        self.last_trace = trace
        return self.ans


class _SumStub:
    def __init__(self, res): self.res = res; self.last_units = None
    def summarize(self, units, *, scope_label=""): self.last_units = units; return self.res


class _QGStub:
    def __init__(self, res): self.res = res
    def generate(self, units, *, n=5, difficulty="orta", seed_question=None): return self.res


def _doc():
    u = [CanonicalUnit(span_id=f"d#{p}.0", doc_id="d", sinif="12", ders="biyoloji",
                       kaynak_turu="ders_kitabi", page=p, bbox=(0, 0, 1, 1), block_no=0,
                       kind="paragraph", text=f"metin {p}", page_visual="mixed",
                       retrieval_disi=False) for p in (10, 11)]
    return CanonicalDoc(source_path="d", doc_id="d", source_version="v", sinif="12",
                        ders="biyoloji", kaynak_turu="ders_kitabi", page_count=11, units=u)


_ANS = GroundedAnswer(text="Cevap [1].", citations=[{"n": 1, "chunk_id": "c1",
                      "span_ids": ["d#10.0"], "pages": [10], "ders": "biyoloji",
                      "doc_id": "d"}],
                      used_source_ids=["c1"], abstained=False, reason="", cost_usd=0.001)


class ChatTests(unittest.TestCase):
    def test_chat_maps_answer_and_role(self):
        g = _GenStub(_ANS)
        svc = RagService(g)
        out = svc.chat({"query": "DNA nedir", "role": {"role": "student", "sinif": "12",
                                                       "ders_list": ["biyoloji"]}})
        self.assertEqual(out["text"], "Cevap [1].")
        self.assertFalse(out["abstained"])
        self.assertEqual(out["citations"][0]["pages"], [10])
        # doc_id backend'e GEÇMELİ: `course_note_file.rag_doc_id` bu anahtardan
        # doldurulur (atıf → korpus eşleşmesi).
        self.assertEqual(out["citations"][0]["doc_id"], "d")
        self.assertEqual(g.last_role.role, Role.STUDENT)          # rol türetildi + geçti
        self.assertEqual(g.last_role.ders_list, ["biyoloji"])

    def test_empty_query_no_generator_call(self):
        g = _GenStub(_ANS)
        out = RagService(g).chat({"query": "   "})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "empty_query")
        self.assertEqual(g.last_role, "UNSET")                    # generator ÇAĞRILMADI

    def test_greeting_is_not_insufficient_data(self):
        g = _GenStub(_ANS)
        svc = RagService(g)
        for q in ("selam", "merhaba"):
            out = svc.chat({"query": q})
            self.assertNotEqual(out["reason"], "insufficient_data", q)
            self.assertFalse(out["abstained"], q)
            self.assertEqual(out["reason"], "", q)
            self.assertEqual(out["citations"], [], q)
            self.assertEqual(out["cost_usd"], 0.0, q)
            self.assertFalse(out["cache_hit"], q)
            self.assertTrue(out["text"].strip(), q)
            self.assertNotIn("bulunamadı", out["text"])
        self.assertEqual(g.last_role, "UNSET")

    def test_non_greeting_question_still_calls_generator(self):
        g = _GenStub(_ANS)
        out = RagService(g).chat({
            "query": "Fotosentez nedir?",
            "role": {"role": "student", "sinif": "12", "ders_list": ["biyoloji"]},
        })
        self.assertNotEqual(g.last_role, "UNSET")
        self.assertEqual(g.last_role.role, Role.STUDENT)
        self.assertEqual(out["text"], "Cevap [1].")
        self.assertFalse(out["abstained"])

    def test_invalid_role_becomes_none(self):
        g = _GenStub(_ANS)
        RagService(g).chat({"query": "q", "role": {"role": "hacker"}})
        self.assertIsNone(g.last_role)                            # tanınmayan rol → None


class SummarizeTests(unittest.TestCase):
    def _svc(self):
        res = GroundedSummary(text="Özet [1].", citations=[{"n": 1, "span_ids": ["d#10.0"],
                              "pages": [10]}], scope_pages=[10, 11], cost_usd=0.02)
        return RagService(_GenStub(_ANS), doc=_doc(), summarizer=_SumStub(res), ders="biyoloji")

    def test_summarize_scope(self):
        out = self._svc().summarize({"scope": {"pages": [10, 11], "scope_label": "x"},
                                     "role": {"role": "student", "sinif": "12", "ders_list": ["biyoloji"]}})
        self.assertEqual(out["text"], "Özet [1].")
        self.assertEqual(out["scope_pages"], [10, 11])

    def test_summarize_empty_scope(self):
        out = self._svc().summarize({"scope": {}})
        self.assertTrue(out["abstained"]); self.assertEqual(out["reason"], "empty_scope")

    def test_summarize_role_denied_wrong_ders(self):
        out = self._svc().summarize({"scope": {"pages": [10]},
                                     "role": {"role": "student", "sinif": "12", "ders_list": ["kimya"]}})
        self.assertTrue(out["abstained"]); self.assertEqual(out["reason"], "role_denied")


class QuestionsTests(unittest.TestCase):
    """#43 ile sözleşme DEĞİŞTİ: rolsüz istek artık fail-CLOSED.

    Bu testin eski hâli `role` GÖNDERMEDEN soru üretilmesini bekliyordu — yani
    EXP-010/SEC-02'deki fail-OPEN davranışının kaydıydı. Koşularak kanıtlanan
    sömürü: tanınmayan rol (`manager`) ya da hiç rol göndermemek, özet/soru
    yollarında erişim kontrolünü TAMAMEN atlatıyordu."""

    def _svc(self):
        qres = GeneratedQuestionSet(items=[GeneratedQuestion("s1", "c1", "kolay")],
                                    span_ids=["d#10.0"], pages=[10], cost_usd=0.01)
        return RagService(_GenStub(_ANS), doc=_doc(), question_gen=_QGStub(qres),
                          ders="biyoloji")

    def test_generate_questions(self):
        out = self._svc().generate_questions(
            {"scope": {"pages": [10]}, "n": 3,
             "role": {"role": "student", "sinif": "12", "ders_list": ["biyoloji"]}})
        self.assertEqual(len(out["items"]), 1)
        self.assertEqual(out["items"][0]["soru"], "s1")
        self.assertEqual(out["pages"], [10])

    def test_generate_questions_without_role_is_denied(self):
        out = self._svc().generate_questions({"scope": {"pages": [10]}, "n": 3})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "role_required")
        self.assertEqual(out["items"], [])


class BudgetWiringTests(unittest.TestCase):
    """#B (#79) — maliyet tavanının KABLOLAMASI: anahtar OKULDUR.

    Ölçülen hata: kapı `check(tenant=school)` ile okula bakıyor, kayıt ise
    `record(tenant=req["tenant"])` ile ESKİ alana yazıyordu. İstemci `tenant`
    göndermediği için okul sayacı hiç dolmuyor → kurum tavanı HİÇ
    tetiklenmiyordu: "koruma" gibi okunan ölü kod, korumadan kötüdür. Özet ve
    soru uçları da harcamayı hiç kaydetmiyordu. Bu testler tavanı GERÇEKTEN
    doldurup reddi gözler."""

    @staticmethod
    def _ans(cost: float) -> GroundedAnswer:
        return GroundedAnswer(text="Cevap [1].", citations=[], used_source_ids=[],
                              abstained=False, reason="", cost_usd=cost)

    @staticmethod
    def _gate(**kw):
        from src.budget import BudgetGate
        return BudgetGate(**kw)

    def test_school_cap_fires_and_is_per_school(self):
        svc = RagService(_GenStub(self._ans(0.30)),
                         budget=self._gate(user_daily_usd=0.0, tenant_monthly_usd=0.50))
        req = {"query": "soru", "school": "okul-a"}
        self.assertEqual(svc.chat(req)["reason"], "")                       # 1) 0,30
        self.assertAlmostEqual(svc.budget.spent(tenant="okul-a"), 0.30)     # KAYIT okula yazıldı
        self.assertEqual(svc.chat(req)["reason"], "")                       # 2) 0,60
        red = svc.chat(req)                                                 # 3) tavan aşıldı
        self.assertEqual(red["reason"], "budget_exceeded")
        self.assertTrue(red["abstained"])
        self.assertEqual(red["cost_usd"], 0.0)
        self.assertEqual(red["citations"], [])
        # Okul başına AYRI kova: B okulu A'nın harcamasından etkilenmez.
        self.assertEqual(svc.chat({"query": "soru", "school": "okul-b"})["reason"], "")
        self.assertAlmostEqual(svc.budget.spent(tenant="okul-b"), 0.30)

    def test_legacy_tenant_field_cannot_bypass_the_school_cap(self):
        """Eski `tenant` alanı tavanı AÇMAZ — anahtar okuldur."""
        svc = RagService(_GenStub(self._ans(0.30)),
                         budget=self._gate(user_daily_usd=0.0, tenant_monthly_usd=0.50))
        svc.budget.record(0.60, tenant="okul-a")            # A okulu dolu
        out = svc.chat({"query": "soru", "school": "okul-a", "tenant": "baska-okul"})
        self.assertEqual(out["reason"], "budget_exceeded")

    def test_summarize_and_questions_record_against_the_school(self):
        """Özet/soru uçları da harcamayı OKUL kovasına yazar (yoksa tavan ölü)."""
        res = GroundedSummary(text="Özet [1].", citations=[], scope_pages=[10], cost_usd=0.30)
        qres = GeneratedQuestionSet(items=[GeneratedQuestion("s1", "c1", "kolay")],
                                    span_ids=["d#10.0"], pages=[10], cost_usd=0.30)
        svc = RagService(_GenStub(_ANS), doc=_doc(), summarizer=_SumStub(res),
                         question_gen=_QGStub(qres), ders="biyoloji",
                         budget=self._gate(user_daily_usd=0.0, tenant_monthly_usd=0.50))
        req = {"school": "okul-a", "scope": {"pages": [10], "scope_label": "x"},
               "role": {"role": "student", "sinif": "12", "ders_list": ["biyoloji"]}}
        ozet = svc.summarize(req)
        self.assertEqual(ozet["reason"], "")
        self.assertAlmostEqual(svc.budget.spent(tenant="okul-a"), 0.30)     # ÖZET kaydedildi
        soru = svc.generate_questions({**req, "n": 1})
        self.assertEqual(soru["reason"], "")
        self.assertAlmostEqual(svc.budget.spent(tenant="okul-a"), 0.60)     # SORULAR da
        red = svc.summarize(req)                                            # tavan aşıldı
        self.assertEqual(red["reason"], "budget_exceeded")
        self.assertTrue(red["abstained"])


class ScopePairTests(unittest.TestCase):
    """rag.chat çift kapsamı: eski `sinif`+`ders_list` yerine (sınıf, ders) ÇİFT
    listesi. Tek çift durumunda AYNI korpus kümesine çözülmeli; çok-çiftte
    KARTEZYEN çarpıma düşmemeli (çapraz-çarpım güvenliği)."""

    def test_single_pair_matches_the_old_shape(self):
        from src.service.handler import _role_ctx
        from src.guard.roles import can_access
        eski = _role_ctx({"role": "student", "sinif": "10", "ders_list": ["biyoloji"]})
        yeni = _role_ctx({"role": "student"}, [{"sinif": "10", "ders": "biyoloji"}])
        self.assertEqual((yeni.sinif, yeni.ders_list), (eski.sinif, eski.ders_list))
        korpuslar = [("10", "biyoloji"), ("10", "satranc"), ("11", "biyoloji")]
        self.assertEqual([can_access(yeni, sinif=s, ders=d) for s, d in korpuslar],
                         [can_access(eski, sinif=s, ders=d) for s, d in korpuslar])
        self.assertEqual([can_access(yeni, sinif=s, ders=d) for s, d in korpuslar],
                         [True, False, False])

    def test_pairs_do_not_open_the_cross_product(self):
        """(10,biyoloji) + (None,satranç) → 10-SATRANÇ açılmamalı; sınıfsız
        kulüp çifti yalnız SINIFSIZ ("" / None) satranç korpusunu açmalı."""
        from src.service.handler import _role_ctx
        from src.guard.roles import can_access
        ctx = _role_ctx({"role": "student"},
                        [{"sinif": "10", "ders": "biyoloji"},
                         {"sinif": None, "ders": "satranc"}])
        self.assertTrue(can_access(ctx, sinif="10", ders="biyoloji"))
        self.assertTrue(can_access(ctx, sinif="", ders="satranc"))
        self.assertFalse(can_access(ctx, sinif="11", ders="satranc"))
        self.assertFalse(can_access(ctx, sinif="10", ders="satranc"))
        self.assertFalse(can_access(ctx, sinif="10", ders="kimya"))

    def test_chat_uses_pairs_when_present(self):
        g = _GenStub(_ANS)
        out = RagService(g).chat({"query": "x", "role": {"role": "student"},
                                  "scope": [{"sinif": "10", "ders": "biyoloji"}]})
        self.assertFalse(out["abstained"])
        self.assertEqual(g.last_role.ders_list, ["biyoloji"])
        self.assertEqual(g.last_role.sinif, "10")

    def test_legacy_dict_scope_is_not_a_grant(self):
        """Özet/soru yolunun sözlük `scope`'u istemci-beyanlı EŞLEŞME girdisidir,
        yetki GRANT'i değildir (SEC-01): ondan grant türetilmemeli."""
        from src.service.handler import _role_ctx
        ctx = _role_ctx({"role": "student", "sinif": "10", "ders_list": ["biyoloji"]},
                        {"sinif": "10", "ders": "satranc"})
        self.assertIsNone(ctx.scope_pairs)
        self.assertEqual(ctx.ders_list, ["biyoloji"])

    def test_registry_routes_the_pair_shape(self):
        """Çift listesi yönlendirmede de çalışmalı (liste `scope` sözlük sanılıp
        500'e düşmemeli)."""
        from src.service.registry import CorpusRegistry
        r = CorpusRegistry()
        r.register(object(), school="okul-a", sinif="10", ders="biyoloji")
        svc, sebep = r.resolve({"school": "okul-a", "scope": [{"sinif": "10", "ders": "biyoloji"}]})
        self.assertIsNotNone(svc)
        self.assertEqual(sebep, "")
        svc2, sebep2 = r.resolve({"school": "okul-a", "scope": [{"sinif": "10", "ders": "kimya"}]})
        self.assertIsNone(svc2)
        self.assertEqual(sebep2, "no_corpus")


if __name__ == "__main__":
    unittest.main()
