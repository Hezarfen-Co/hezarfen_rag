"""Sahte okul — backend biçiminde tam veri kümesi + yetki taklidi.

NEDEN YETKİ TAKLİDİ ŞART: sahte okuyucu her kullanıcıya her şeyi döndürseydi
kasa izolasyonu testlerimiz **hiçbir şey ölçmezdi** — gerçek bir sızıntı olsa
da yeşil kalırlardı. Bu yüzden `FakeSchool` backend'in görünürlük kurallarını
taklit eder ve bu dosya o taklidin kendisini sınar.
"""
import os
import unittest

from src.bridge.student import build_context
from src.demo.school import School, FakeSchool, build_school
from src.guard.roles import can_access

_VAR = os.path.isdir(os.path.join("data", "lise", "10"))


@unittest.skipUnless(_VAR, "data/lise/10 yok")
class OkulKurmaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.o = build_school()
        cls.s = FakeSchool(cls.o)

    def _uid(self, username):
        return self.o.user_by_name(username)["id"]

    def test_school_has_every_record_kind(self):
        summary = self.o.summary()
        for alan in ("user_by_name", "sube", "uyelik", "ders", "kayit",
                     "kisisel_not", "ders_notu", "veli_bagi"):
            self.assertGreater(summary[alan], 0, f"{alan} bos")

    def test_roles_cover_the_product_hierarchy(self):
        roller = {u["role"] for u in self.o.users}
        self.assertEqual(roller, {"student", "teacher", "parent"})

    def test_ids_are_deterministic(self):
        self.assertEqual(self.o.to_dict()["users"], build_school().to_dict()["users"])

    def test_every_enrollment_points_at_a_real_course_and_user(self):
        kurslar = {c["id"] for c in self.o.courses}
        kisiler = {u["id"] for u in self.o.users}
        for e in self.o.enrollments:
            self.assertIn(e["course"], kurslar)
            self.assertIn(e["user"], kisiler)

    def test_every_course_note_points_at_a_real_course(self):
        kurslar = {c["id"] for c in self.o.courses}
        for n in self.o.course_notes:
            self.assertIn(n["course"], kurslar)

    def test_sections_differ_so_isolation_is_measurable(self):
        """Tek ders kümesi olsaydı 'aynı sınıf, farklı ders' durumu hiç
        kurulmaz ve izolasyonun ders boyutu ölçülemezdi."""
        a = build_context(self.s, self._uid("ogrenci1")).dersler      # 10-A
        b = build_context(self.s, self._uid("ogrenci2")).dersler      # 10-B
        self.assertNotEqual(set(a), set(b))
        self.assertTrue(set(a) & set(b), "şubeler hiç örtüşmüyor")


@unittest.skipUnless(_VAR, "data/lise/10 yok")
class GorunurlukTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.o = build_school()
        cls.s = FakeSchool(cls.o)

    def _uid(self, username):
        return self.o.user_by_name(username)["id"]

    def test_ai_principal_alone_sees_nothing(self):
        """`on_behalf_of` yoksa istek servisin kendi (`ai`) kimliğiyle koşar ve
        `ai` okul verisini göremez — backend'in kendi ifadesi."""
        for path in ("/users/me", "/classes", "/courses", "/notes"):
            self.assertEqual(self.s.get(path)[0], 403, path)

    def test_student_sees_only_their_own_notes(self):
        a = build_context(self.s, self._uid("ogrenci1"))
        b = build_context(self.s, self._uid("ogrenci2"))
        self.assertTrue(a.notlar)
        self.assertTrue(b.notlar)
        self.assertEqual({n.id for n in a.notlar} & {n.id for n in b.notlar}, set())

    def test_student_cannot_read_a_course_they_are_not_in(self):
        b = build_context(self.s, self._uid("ogrenci2"))          # 10-B
        a_dersleri = {c["id"] for c in self.o.courses
                      if c["title"] == "Biyoloji"}
        for kurs in a_dersleri:
            self.assertEqual(
                self.s.get("/course-notes", query=f"course={kurs}",
                           on_behalf_of=b.user_id)[0], 403)

    def test_vault_isolation_follows_enrollment_not_just_grade(self):
        """İki öğrenci de 10. sınıfta ama farklı derslerde — sınıf eşitse bile
        ders kayıtsızsa erişim REDDEDİLMELİ."""
        a = build_context(self.s, self._uid("ogrenci1")).role_context()
        b = build_context(self.s, self._uid("ogrenci2")).role_context()
        self.assertTrue(can_access(a, sinif="10", ders="biyoloji"))
        self.assertFalse(can_access(b, sinif="10", ders="biyoloji"))
        self.assertTrue(can_access(b, sinif="10", ders="fl-kimya"))
        self.assertFalse(can_access(a, sinif="10", ders="fl-kimya"))

    def test_no_student_can_reach_another_grade(self):
        for kul in ("ogrenci1", "ogrenci2"):
            ctx = build_context(self.s, self._uid(kul)).role_context()
            for sinif in ("9", "11", "12"):
                self.assertFalse(can_access(ctx, sinif=sinif, ders="biyoloji"),
                                 f"{kul} sinif {sinif}'e erisebildi")

    def test_teacher_sees_their_own_section(self):
        t = build_context(self.s, self._uid("ogretmen1"))
        self.assertEqual(t.rol, "teacher")
        self.assertEqual(t.sinif, "10")
        self.assertTrue(t.dersler)

    def test_parent_path_is_explicitly_unimplemented(self):
        """Veli yolu KURULMADI ve bu test onu kayda geçirir.

        `parent_links` üretiliyor ama veli hiçbir şey göremiyor. Sebep:
        velinin çocuğunun verisine hangi uçtan eriştiği backend'de henüz
        doğrulanmadı. Uydurulmuş bir veli görünürlüğü, üzerine kurulacak her
        izolasyon ölçümünü sessizce geçersiz kılardı. Veli yolu açıldığında
        bu test DEĞİŞMELİ (BL-011)."""
        veli = self._uid("veli1")
        self.assertTrue(self.o.parent_links)
        for path in ("/classes", "/courses", "/notes"):
            durum, govde = self.s.get(path, on_behalf_of=veli)
            self.assertEqual(durum, 200)
            self.assertEqual(govde["total"], 0, f"{path} veli icin dolu geldi")

    def test_unknown_user_is_404_not_an_open_door(self):
        self.assertEqual(self.s.get("/users/me", on_behalf_of="01YOK")[0], 404)

    def test_course_notes_without_course_param_is_a_bad_request(self):
        self.assertEqual(
            self.s.get("/course-notes", on_behalf_of=self._uid("ogrenci1"))[0], 400)

    def test_reads_are_recorded_with_the_identity_used(self):
        s = FakeSchool(self.o)
        uid = self._uid("ogrenci1")
        build_context(s, uid)
        self.assertTrue(s.calls)
        for _path, _q, obo in s.calls:
            self.assertEqual(obo, uid)


@unittest.skipUnless(_VAR, "data/lise/10 yok")
class DiskeYazmaTests(unittest.TestCase):
    def test_writes_full_dataset_and_per_user_snapshots(self):
        import tempfile
        from src.bridge.client import FakeReader
        from src.demo.school import write
        o = build_school()
        with tempfile.TemporaryDirectory() as d:
            yazilan = write(o, d)
            self.assertIn(os.path.join(d, "okul.json"), yazilan)
            anlik = os.path.join(d, "okuma-ogrenci1.json")
            self.assertTrue(os.path.isfile(anlik))
            # anlık görüntüden kurulan bağlam, canlı sahteyle AYNI olmalı
            b1 = build_context(FakeReader.from_snapshot(anlik),
                            o.user_by_name("ogrenci1")["id"])
            b2 = build_context(FakeSchool(o), o.user_by_name("ogrenci1")["id"])
            self.assertEqual(b1.dersler, b2.dersler)
            self.assertEqual([n.id for n in b1.notlar], [n.id for n in b2.notlar])


class KorpussuzTests(unittest.TestCase):
    def test_refuses_a_grade_with_no_corpus(self):
        """Korpusta veri yoksa senaryo UYDURULMAZ, hata verilir.

        DİKKAT: bu test önce `sinif="11"` kullanıyordu ve "bu makinede 11.
        sınıf verisi yok" gibi **geçici bir ortam gerçeğini** sözleşme sanıyordu.
        EBA indirmesi 11. sınıfı getirince test kırıldı. Artık boş bir geçici
        kök kullanılıyor: koşul veriden bağımsız."""
        import tempfile
        with tempfile.TemporaryDirectory() as bos:
            with self.assertRaises(ValueError):
                build_school(kok=bos, sinif="10")

    def test_refuses_an_out_of_band_grade(self):
        with self.assertRaises(ValueError):
            build_school(sinif="13")

    def test_empty_school_summary_is_all_zero(self):
        self.assertEqual(School(slug="x").summary()["user_by_name"], 0)


if __name__ == "__main__":
    unittest.main()
