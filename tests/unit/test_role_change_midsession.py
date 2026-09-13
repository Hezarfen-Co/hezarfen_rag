"""#M3-10 (EVAL-16) — OTURUM ORTASINDA rol değişimi.

ÖLÇÜLEN DURUM: rol değişimi hiç test edilmemiş. Bütün rol testleri tek bir
`RoleContext` ile tek istek ölçüyor.

ÜRÜN AÇISINDAN NE DEMEK: rol gerçekte DEĞİŞİR. Öğrenci seçmeli dersi bırakır,
öğretmenin ders ataması kaldırılır, veli-öğrenci hesabı aynı cihazda
değişir, dönem biter ve sınıf 10'dan 11'e geçer. Değişimden SONRA gelen
istek eski yetkiyle cevaplanırsa bu bir YETKİ SIZINTISIDIR ve cevap
cache'ten geldiği için hiçbir yerde iz bırakmaz.

İKİ AYRI KIRILMA NOKTASI VAR:
  1. Servis rolü istek başına yeniden türetiyor mu, yoksa ilkini mi tutuyor?
  2. Cache anahtarı rolü taşıyor mu? Taşımazsa yetki katmanı doğru karar
     verse bile ESKİ CEVAP dönebilir.
"""
import unittest

from src.generate.generator import _role_cache_key
from src.guard.roles import Role, RoleContext, can_access
from src.service import RagService
from tests.unit.test_service import _ANS, _GenStub, _doc


def _role(sinif="10", dersler=("biyoloji",), role="student"):
    return {"role": role, "sinif": sinif, "ders_list": list(dersler)}


class RoleIsDerivedPerRequestTests(unittest.TestCase):
    """Servis durumsuzdur: her istekte rol yeniden türetilmeli."""

    def test_second_request_sees_the_new_role(self):
        g = _GenStub(_ANS)
        svc = RagService(g)
        svc.chat({"query": "s", "role": _role(dersler=["biyoloji", "fizik"])})
        ilk = g.last_role
        svc.chat({"query": "s", "role": _role(dersler=["biyoloji"])})
        self.assertEqual(ilk.ders_list, ["biyoloji", "fizik"])
        self.assertEqual(g.last_role.ders_list, ["biyoloji"],
                         "servis ILK rolu tutuyor -- daraltma etkisiz")

    def test_role_widening_also_applies(self):
        """Daralma kadar genişleme de geçmeli; aksi hâlde öğretmene yeni ders
        atandığında ürün 'yetkiniz yok' demeye devam ederdi."""
        g = _GenStub(_ANS)
        svc = RagService(g)
        svc.chat({"query": "s", "role": _role(role="student")})
        svc.chat({"query": "s", "role": _role(role="teacher",
                                             dersler=["biyoloji", "fizik"])})
        self.assertEqual(g.last_role.role, Role.TEACHER)

    def test_removing_the_role_does_not_fall_back_to_the_previous_one(self):
        """Rolsüz istek, bir öncekinin rolüyle cevaplanmamalı."""
        g = _GenStub(_ANS)
        svc = RagService(g)
        svc.chat({"query": "s", "role": _role(role="admin")})
        svc.chat({"query": "s"})
        self.assertIsNone(g.last_role, "onceki istegin rolu sizdi")


class CacheKeyCarriesRoleTests(unittest.TestCase):
    """Yetki doğru karar verse bile cache eski cevabı dönebilir."""

    def test_narrowing_subjects_changes_the_key(self):
        genis = _role_cache_key(RoleContext(Role.STUDENT, "10", ["biyoloji", "fizik"]))
        dar = _role_cache_key(RoleContext(Role.STUDENT, "10", ["biyoloji"]))
        self.assertNotEqual(genis, dar)

    def test_grade_change_changes_the_key(self):
        """Dönem sonunda 10 -> 11. Aynı soru, farklı kitap."""
        self.assertNotEqual(
            _role_cache_key(RoleContext(Role.STUDENT, "10", ["biyoloji"])),
            _role_cache_key(RoleContext(Role.STUDENT, "11", ["biyoloji"])))

    def test_role_type_changes_the_key(self):
        """Öğretmene verilen cevap öğrenciye sızmamalı (ölçme-değerlendirme
        içeriği öğretmen görünümünde farklı olabilir)."""
        self.assertNotEqual(
            _role_cache_key(RoleContext(Role.TEACHER, "10", ["biyoloji"])),
            _role_cache_key(RoleContext(Role.STUDENT, "10", ["biyoloji"])))

    def test_subject_order_does_not_change_the_key(self):
        """Backend listeyi farklı sırada gönderirse cache boşuna ıskalamamalı
        — sıra yetkinin bir parçası değildir."""
        self.assertEqual(
            _role_cache_key(RoleContext(Role.STUDENT, "10", ["fizik", "biyoloji"])),
            _role_cache_key(RoleContext(Role.STUDENT, "10", ["biyoloji", "fizik"])))

    def test_roleless_key_differs_from_a_role_key(self):
        self.assertNotEqual(
            _role_cache_key(None),
            _role_cache_key(RoleContext(Role.STUDENT, "10", ["biyoloji"])))


class NarrowedAuthorizationTakesEffectTests(unittest.TestCase):
    """`can_access` daralmayı ANINDA uygulamalı."""

    def test_removed_subject_is_denied(self):
        onceki = RoleContext(Role.STUDENT, "10", ["biyoloji", "fizik"])
        sonraki = RoleContext(Role.STUDENT, "10", ["biyoloji"])
        self.assertTrue(can_access(onceki, sinif="10", ders="fizik"))
        self.assertFalse(can_access(sonraki, sinif="10", ders="fizik"))

    def test_empty_subject_list_denies_all(self):
        """Atama kaldırıldı ama rol duruyor: no-leak deny."""
        self.assertFalse(can_access(RoleContext(Role.TEACHER, "10", []),
                                    sinif="10", ders="biyoloji"))

    def test_grade_change_closes_the_old_grade(self):
        yeni = RoleContext(Role.STUDENT, "11", ["biyoloji"])
        self.assertFalse(can_access(yeni, sinif="10", ders="biyoloji"))


class SummaryAndQuestionPathTests(unittest.TestCase):
    """Erişim yeniden-doğrulaması yalnız `chat`'te değil, her uçta olmalı.

    #42/#43: tanınmayan rol `_role_ctx`ten None dönünce `if role_ctx is not
    None:` koruması erişim kontrolünü TAMAMEN atlıyordu (fail-OPEN).
    """

    def _svc(self):
        from src.summarize.summarizer import GroundedSummary
        from src.generate.question_gen import GeneratedQuestionSet
        from tests.unit.test_service import _QGStub, _SumStub
        return RagService(
            _GenStub(_ANS), doc=_doc(),
            summarizer=_SumStub(GroundedSummary(
                text="ozet [1].", citations=[], cost_usd=0.0)),
            question_gen=_QGStub(GeneratedQuestionSet(items=[], cost_usd=0.0)),
            ders="biyoloji")

    def test_summary_denies_the_narrowed_role(self):
        svc = self._svc()
        istek = {"scope": {"pages": [10]}, "role": _role(sinif="12", dersler=["biyoloji"])}
        genis = svc.summarize(dict(istek))
        dar = svc.summarize({"scope": {"pages": [10]},
                             "role": _role(sinif="12", dersler=["fizik"])})
        self.assertFalse(genis.get("abstained"), "gecerli rol reddedildi")
        self.assertTrue(dar.get("abstained"), "daraltilmis rol ozeti aldi")

    def test_unknown_role_is_not_fail_open(self):
        svc = self._svc()
        out = svc.summarize({"scope": {"pages": [10]},
                             "role": {"role": "mudur_yardimcisi", "sinif": "12",
                                      "ders_list": ["biyoloji"]}})
        self.assertTrue(out.get("abstained"),
                        "taninmayan rol sinirsiz yetkiye donusuyor (fail-OPEN)")


if __name__ == "__main__":
    unittest.main()
