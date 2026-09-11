"""Öğrenci bağlamı: backend kimliği → ürün kasa izolasyonu.

NEDEN: erişim kararımız `RoleContext(role, sinif, ders_list)` ister ama backend
bu üçlüyü tek yerde tutmaz — rol `User`'da, sınıf üyesi olunan `ClassGroup`'un
`grade`'inde, dersler `Enrollment`→`Course.title`'da. Üçü birleştirilmeden
izolasyon kurulamaz; yanlış birleştirilirse ya sessiz DENY (öğrenci kendi
dersini göremez) ya da sızıntı olur.
"""
import unittest

from src.backend.ders_eslesme import ders_slug, kasa_for, katla, korpus_dersleri
from src.backend.istemci import SahteOkuyucu
from src.backend.ogrenci import baglam_kur
from src.backend.senaryo import _BASLIK
from src.guard.roles import Role, can_access


def _tablo(degis=None):
    t = {
        ("/users/me", None): (200, {"id": "01STU", "username": "ogrenci1",
                                    "name": "Zeynep", "surname": "Kaya",
                                    "role": "student"}),
        ("/classes", None): (200, {"items": [{"id": "01CLS", "name": "10-A",
                                              "grade": "10"}], "total": 1}),
        ("/courses", None): (200, {"items": [{"id": "01C1", "title": "Biyoloji"}],
                                   "total": 1}),
        ("/notes", None): (200, {"items": [], "total": 0}),
        ("/course-notes", "course=01C1"): (200, {"items": [], "total": 0}),
    }
    t.update(degis or {})
    return t


class DersEslesmeTests(unittest.TestCase):
    def test_turkish_case_folding(self):
        """`str.lower()` TEK BAŞINA YETMEZ: 'İNGİLİZCE'.lower() Türkçe olmayan
        yerelde birleşen noktalı i üretir ve eşleşme kaçar."""
        self.assertEqual(ders_slug("İNGİLİZCE"), "ingilizce")
        self.assertEqual(ders_slug("ingilizce"), "ingilizce")
        self.assertEqual(katla("Coğrafya"), katla("COĞRAFYA"))

    def test_unknown_title_returns_none_not_a_guess(self):
        """Uydurma slug üretmek, var olmayan bir kasaya izin gibi görünür."""
        self.assertIsNone(ders_slug("Astroloji"))
        self.assertIsNone(ders_slug(""))
        self.assertIsNone(ders_slug(None))

    def test_round_trip_is_total(self):
        """KOŞULARAK BULUNDU: `_BASLIK['bilisim']` = 'Bilişim Teknolojileri'
        idi ama eşleme tablosunda o biçim YOKTU → gerçek bir ders 'tanınmayan'
        sayılıp `ders_list` dışında kalıyordu, yani öğrenci kendi dersini
        göremeyecekti (sessiz DENY). Her başlık kendi slug'ına dönmeli."""
        kirik = [(slug, baslik) for slug, baslik in _BASLIK.items()
                 if ders_slug(baslik) != slug]
        self.assertEqual(kirik, [])

    def test_kasa_bands(self):
        self.assertEqual(kasa_for(5), "ortaokul")
        self.assertEqual(kasa_for(8), "ortaokul")
        self.assertEqual(kasa_for(9), "lise")
        self.assertEqual(kasa_for("12"), "lise")
        self.assertIsNone(kasa_for(4))
        self.assertIsNone(kasa_for(13))
        self.assertIsNone(kasa_for("hazirlik"))

    def test_corpus_subjects_come_from_disk_not_the_table(self):
        """Eşleme tablosu değil, dosya sistemi gerçeği ölçüttür."""
        self.assertEqual(korpus_dersleri("data", "lise", "99"), [])


class BaglamKurmaTests(unittest.TestCase):
    def test_grade_comes_from_the_class_not_the_user(self):
        b = baglam_kur(SahteOkuyucu(_tablo()), "01STU")
        self.assertEqual(b.sinif, "10")
        self.assertEqual(b.sube, "10-A")
        self.assertEqual(b.kasa, "lise")

    def test_reads_run_on_behalf_of_the_student(self):
        """Yetki backend'de kalmalı: `ai` görevlisi okul verisini göremez,
        öğrenci yalnız kendi görebildiğini görür."""
        o = SahteOkuyucu(_tablo())
        baglam_kur(o, "01STU")
        self.assertTrue(o.cagrilar)
        for path, _query, obo in o.cagrilar:
            self.assertEqual(obo, "01STU", f"{path} ogrenci adina okunmadi")

    def test_role_context_feeds_vault_isolation(self):
        ctx = baglam_kur(SahteOkuyucu(_tablo()), "01STU").role_context()
        self.assertEqual(ctx.role, Role.STUDENT)
        self.assertTrue(can_access(ctx, sinif="10", ders="biyoloji"))
        self.assertFalse(can_access(ctx, sinif="11", ders="biyoloji"))
        self.assertFalse(can_access(ctx, sinif="10", ders="fizik"))

    def test_unknown_course_is_excluded_not_guessed(self):
        t = _tablo({("/courses", None): (200, {"items": [
            {"id": "01C1", "title": "Biyoloji"},
            {"id": "01C9", "title": "Astroloji"}], "total": 2})})
        b = baglam_kur(SahteOkuyucu(t), "01STU")
        self.assertEqual(b.dersler, ["biyoloji"])
        self.assertEqual(b.taninmayan_dersler, ["Astroloji"])
        self.assertFalse(can_access(b.role_context(), sinif="10", ders="astroloji"))

    def test_no_class_means_no_grade_and_deny(self):
        """FAIL-CLOSED: şube yoksa sınıf yok; sınıf yoksa hiçbir şey açılmaz."""
        t = _tablo({("/classes", None): (200, {"items": [], "total": 0})})
        b = baglam_kur(SahteOkuyucu(t), "01STU")
        self.assertIsNone(b.sinif)
        self.assertIsNone(b.kasa)
        self.assertFalse(can_access(b.role_context(), sinif="10", ders="biyoloji"))

    def test_class_without_grade_is_skipped(self):
        """`grade` Option<ClassGrade> — boş olabilir. Boş grade'i '' diye
        kabul etmek `sinif=''` üretir ve hiçbir şeye eşleşmez."""
        t = _tablo({("/classes", None): (200, {"items": [
            {"id": "01X", "name": "Satranç Kulübü"},
            {"id": "01CLS", "name": "10-A", "grade": "10"}], "total": 2})})
        b = baglam_kur(SahteOkuyucu(t), "01STU")
        self.assertEqual(b.sinif, "10")

    def test_no_enrollment_means_empty_ders_list_and_total_deny(self):
        """`ders_list` boş == 'henüz hiçbir derse atanmamış' → no-leak deny."""
        t = _tablo({("/courses", None): (200, {"items": [], "total": 0})})
        b = baglam_kur(SahteOkuyucu(t), "01STU")
        self.assertEqual(b.dersler, [])
        self.assertFalse(can_access(b.role_context(), sinif="10", ders="biyoloji"))

    def test_unresolvable_role_yields_no_context(self):
        """#43 dersi: tanınmayan rol `None` vermeli — o kontrolü ATLATMAMALI."""
        t = _tablo({("/users/me", None): (200, {"id": "01X", "username": "u",
                                                  "role": "Öğrenci"})})
        b = baglam_kur(SahteOkuyucu(t), "01X")
        self.assertIsNone(b.role_context())
        self.assertFalse(can_access(b.role_context(), sinif="10", ders="biyoloji"))

    def test_missing_user_raises(self):
        t = _tablo({("/users/me", None): (404, None)})
        with self.assertRaises(ValueError):
            baglam_kur(SahteOkuyucu(t), "01STU")

    def test_plain_list_body_is_accepted(self):
        """Bazı uçlar sayfalı (`{items,...}`), bazıları düz liste döner."""
        t = _tablo({("/notes", None): (200, [{"id": "01N", "title": "t",
                                                "content": "c"}])})
        b = baglam_kur(SahteOkuyucu(t), "01STU")
        self.assertEqual(len(b.notlar), 1)

    def test_denied_course_notes_do_not_break_the_context(self):
        """Erişimi olmayan derse 403 dönerse bağlam yine kurulmalı."""
        t = _tablo({("/course-notes", "course=01C1"): (403, None)})
        b = baglam_kur(SahteOkuyucu(t), "01STU")
        self.assertEqual(b.ders_notlari, [])
        self.assertEqual(b.dersler, ["biyoloji"])


class RestOkuyucuSinirTests(unittest.TestCase):
    def test_rest_refuses_to_read_as_someone_else(self):
        """HTTP'de kim giriş yaptıysa o okur. Sessizce yanlış kullanıcının
        verisini döndürmek, izolasyon ölçümlerimizi geçersiz kılardı."""
        from src.backend.istemci import RestOkuyucu
        r = RestOkuyucu("http://yok", school="demo", session_token="t",
                        kendi_user_id="01ME")
        with self.assertRaises(ValueError):
            r.get("/notes", on_behalf_of="01BASKASI")


if __name__ == "__main__":
    unittest.main()
