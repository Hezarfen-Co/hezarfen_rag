"""#42 + #43 — özet/soru yollarında DÜŞMANCA yetki testleri.

NEDEN (EXP-010/SEC-01 + SEC-02, ikisi de KOŞULARAK kanıtlanmıştı):

SEC-01 (KRİTİK): `handler.summarize`/`generate_questions` erişim kararını
istemcinin gövdede gönderdiği `scope.sinif`/`scope.ders` ile veriyordu
(`scope.get("sinif") or getattr(self.doc,"sinif")`) → saldırgan `can_access`'e
hem özneyi hem **nesneyi** kendisi bildiriyordu. Sömürü: 9. sınıf matematik
öğrencisi **gerçek rolüyle** `scope={"sinif":"9","ders":"matematik"}` gönderip
12-biyoloji içeriğini özetletti. Mevcut test (`test_summarize_role_denied_wrong_ders`)
yalnız *dürüst* saldırganı deniyordu → **yanlış güvence veriyordu**.

SEC-02 (KRİTİK): rol çözülemezse (`manager` enum'da YOKTU, `"Öğrenci"`, boş)
`_role_ctx` None dönüyor ve `if role_ctx is not None:` koruması yüzünden kontrol
**tamamen atlanıyordu** (fail-OPEN).

Bu dosya sömürüleri kalıcı test hâline getirir — bir daha sessizce açılamaz.
"""
import unittest
from dataclasses import dataclass, field

from src.service.handler import RagService


@dataclass
class _Unit:
    span_id: str = "d#40.0"
    page: int = 40
    text: str = "12. SINIF BIYOLOJI GIZLI ICERIK: DNA replikasyonu..."
    kind: str = "paragraph"
    retrieval_disi: bool = False
    retrievable: bool = True
    doc_id: str = "doc"
    sinif: str = "12"
    ders: str = "biyoloji"
    kaynak_turu: str = "ders_kitabi"
    bbox: tuple = (0, 0, 1, 1)
    block_no: int = 0
    page_visual: str = "low_visual"


@dataclass
class _Doc:
    """Servis 12/biyoloji için ayağa kalkmış (gerçek üretim kurulumu)."""
    sinif: str = "12"
    ders: str = "biyoloji"
    doc_id: str = "doc"
    source_version: str = "v1"
    units: list = field(default_factory=lambda: [_Unit()])


class _SumStub:
    """Çağrılırsa SIZINTI olmuştur — çağrılıp çağrılmadığını kaydeder."""

    def __init__(self):
        self.called = False

    def summarize(self, units, scope_label=""):
        self.called = True
        from src.summarize.summarizer import GroundedSummary
        return GroundedSummary(text="OZET(SIZDI): " + units[0].text,
                               citations=[], scope_pages=[40], cost_usd=0.01)


class _QGStub:
    def __init__(self):
        self.called = False

    def generate(self, units, n=5, difficulty="orta", seed_question=None):
        self.called = True
        from src.generate.question_gen import GeneratedQuestion, GeneratedQuestionSet
        return GeneratedQuestionSet(items=[GeneratedQuestion("s", "c", "orta")],
                                    span_ids=["d#40.0"], pages=[40], cost_usd=0.01)


class _GenStub:
    def answer(self, *a, **kw):
        from src.generate.generator import GroundedAnswer
        return GroundedAnswer(text="x", citations=[], abstained=False, reason="")


def _svc():
    return RagService(_GenStub(), doc=_Doc(), summarizer=_SumStub(),
                      question_gen=_QGStub(), ders="biyoloji")


# 9. sınıf matematik öğrencisinin auth'un ürettiği GERÇEK rolü
_ROL_9MAT = {"role": "student", "sinif": "9", "ders_list": ["matematik"]}
_ROL_12BIO = {"role": "student", "sinif": "12", "ders_list": ["biyoloji"]}


class ClientScopeSpoofingTests(unittest.TestCase):
    """SEC-01: istemci kendi kapsamını "beyan ederek" yetki yükseltemez."""

    def test_spoofed_scope_is_rejected(self):
        svc = _svc()
        out = svc.summarize({"scope": {"pages": [40], "sinif": "9",
                                       "ders": "matematik"},
                             "role": _ROL_9MAT})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "scope_mismatch")
        self.assertFalse(svc.summarizer.called, "summarizer çağrıldı → SIZINTI")
        self.assertNotIn("GIZLI", out["text"])

    def test_spoofed_scope_rejected_on_questions_path_too(self):
        svc = _svc()
        out = svc.generate_questions({"scope": {"pages": [40], "sinif": "9",
                                                "ders": "matematik"},
                                      "role": _ROL_9MAT})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "scope_mismatch")
        self.assertEqual(out["items"], [])
        self.assertFalse(svc.question_gen.called)

    def test_honest_attacker_still_denied(self):
        """Dürüst scope ile de reddedilmeli (eski test bunu zaten yakalıyordu)."""
        svc = _svc()
        out = svc.summarize({"scope": {"pages": [40]}, "role": _ROL_9MAT})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "role_denied")
        self.assertFalse(svc.summarizer.called)

    def test_partial_spoof_only_ders(self):
        svc = _svc()
        out = svc.summarize({"scope": {"pages": [40], "ders": "matematik"},
                             "role": _ROL_9MAT})
        self.assertEqual(out["reason"], "scope_mismatch")

    def test_legitimate_matching_scope_is_allowed(self):
        """Doğru rol + sunucu gerçeğiyle EŞLEŞEN kapsam → geçer."""
        svc = _svc()
        out = svc.summarize({"scope": {"pages": [40], "sinif": "12",
                                       "ders": "biyoloji"},
                             "role": _ROL_12BIO})
        self.assertFalse(out["abstained"])
        self.assertTrue(svc.summarizer.called)

    def test_legitimate_without_scope_labels_is_allowed(self):
        svc = _svc()
        out = svc.summarize({"scope": {"pages": [40]}, "role": _ROL_12BIO})
        self.assertFalse(out["abstained"])


class UnknownRoleFailClosedTests(unittest.TestCase):
    """SEC-02: rol çözülemezse erişim AÇILMAZ."""

    def test_manager_is_now_a_real_role(self):
        """Ürün hiyerarşisi parent<student<teacher<manager<admin; `manager`
        enum'da yoktu ve bu yüzden SINIRSIZ yetkiye dönüşüyordu."""
        from src.guard.roles import Role
        self.assertEqual(Role("manager"), Role.MANAGER)

    def test_manager_gets_access_as_authorised_role(self):
        svc = _svc()
        out = svc.summarize({"scope": {"pages": [40]},
                             "role": {"role": "manager", "sinif": "9",
                                      "ders_list": []}})
        self.assertFalse(out["abstained"])   # yetkili — ama artık BİLİNÇLİ olarak

    def test_missing_role_is_denied(self):
        svc = _svc()
        out = svc.summarize({"scope": {"pages": [40]}})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "role_required")
        self.assertFalse(svc.summarizer.called)

    def test_unresolvable_role_is_denied(self):
        """Role enum'una ÇÖZÜLEMEYEN değerler → role_required (fail-closed)."""
        for bad in ({"role": "hacker"}, {"role": ""}, {"role": "Öğrenci"},
                    {"role": None}):
            svc = _svc()
            out = svc.summarize({"scope": {"pages": [40]}, "role": bad})
            with self.subTest(role=bad):
                self.assertTrue(out["abstained"])
                self.assertEqual(out["reason"], "role_required")
                self.assertFalse(svc.summarizer.called)

    def test_normalisable_role_resolves_then_scope_check_applies(self):
        """DÜZELTME: EXP-010 `"STUDENT "` için de "çözülemez" demişti; aslında
        `_role_ctx` `.strip().lower()` uyguladığı için GEÇERLİ role çözülüyor.
        Sonuç yine RED ama gerekçe farklı (kapsam kontrolü uygulanıyor) — yani
        bu değer bir fail-open yolu DEĞİLDİ. Her iki durumda da erişim kapalı."""
        svc = _svc()
        out = svc.summarize({"scope": {"pages": [40]},
                             "role": {"role": "STUDENT ", "sinif": "9",
                                      "ders_list": ["matematik"]}})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "role_denied")
        self.assertFalse(svc.summarizer.called)

    def test_non_dict_role_is_denied(self):
        for bad in ("student", ["student"], 42):
            svc = _svc()
            out = svc.generate_questions({"scope": {"pages": [40]}, "role": bad})
            with self.subTest(role=bad):
                self.assertEqual(out["reason"], "role_required")

    def test_empty_ders_list_still_denied(self):
        """`ders_list` boş = derse atanmamış → no-leak deny (DEĞİŞMEDİ)."""
        svc = _svc()
        out = svc.summarize({"scope": {"pages": [40]},
                             "role": {"role": "student", "sinif": "12",
                                      "ders_list": []}})
        self.assertEqual(out["reason"], "role_denied")


class GateIsSingleSourceTests(unittest.TestCase):
    def test_both_paths_use_the_same_gate(self):
        """İki yol ayrı ayrı yazılırsa biri tekrar açılır — tek fonksiyon olmalı."""
        import inspect
        from src.service import handler
        src_sum = inspect.getsource(handler.RagService.summarize)
        src_q = inspect.getsource(handler.RagService.generate_questions)
        for src in (src_sum, src_q):
            self.assertIn("_scope_denied", src)
            # eski fail-open deseni geri gelmesin
            self.assertNotIn("if role_ctx is not None:", src)
            self.assertNotIn('scope.get("sinif") or', src)


if __name__ == "__main__":
    unittest.main()
