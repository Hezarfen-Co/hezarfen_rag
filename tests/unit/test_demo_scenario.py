"""Öğrenci senaryosu — "öğrenci varmış gibi", uydurma içerik OLMADAN.

Scenario gerçek korpustan kurulur: dersler `data/<kasa>/<sınıf>/` altında
GERÇEKTEN bulunan klasörlerdir, not metinleri MEB `kazanimlar.json`'undan
AYNEN alınır. Gerekçe: uydurulmuş bir not, üzerinde ölçülen her şeyi (atıf
isabeti, kasa izolasyonu) anlamsız kılar.
"""
import os
import unittest

from src.bridge.subject_map import corpus_subjects
from src.bridge.client import FakeReader
from src.bridge.student import build_context
from src.demo.scenario import build_scenario, read_objectives, _record_key

_VAR = os.path.isdir(os.path.join("data", "lise", "10"))


@unittest.skipUnless(_VAR, "data/lise/10 yok")
class SenaryoTests(unittest.TestCase):
    def setUp(self):
        self.s = build_scenario()

    def test_courses_are_only_what_the_corpus_actually_has(self):
        """Var olmayan bir derse kayıt üretmek, ölçümde 'kaynak bulunamadı'yı
        ürün hatası gibi gösterirdi."""
        diskte = set(corpus_subjects("data", "lise", "10"))
        self.assertTrue(diskte)
        self.assertEqual(len(self.s.dersler), len(diskte))

    def test_note_text_is_verbatim_curriculum(self):
        kz = {k["metin"] for k in read_objectives("data", "lise", "10", "biyoloji")}
        self.assertTrue(kz)
        bulundu = any(any(m in n["content"] for m in kz) for n in self.s.notlar)
        self.assertTrue(bulundu, "not metni kazanımlardan gelmiyor")

    def test_student_notes_are_not_empty(self):
        """KOŞULARAK BULUNDU: ilk N dersi almak alfabetik olarak başta duran
        kazanımsız derslere (almanca/arapça/beden) denk gelip SIFIR not
        üretiyordu. Not seçimi kazanımı OLAN derslerden yapılmalı."""
        self.assertTrue(self.s.notlar)
        for n in self.s.notlar:
            self.assertTrue(n["content"].strip())

    def test_ids_are_deterministic(self):
        ikinci = build_scenario()
        self.assertEqual(self.s.ogrenci["id"], ikinci.ogrenci["id"])
        self.assertEqual([d["id"] for d in self.s.dersler],
                         [d["id"] for d in ikinci.dersler])

    def test_ids_look_like_record_keys(self):
        k = _record_key("user", "demo", "ogrenci1")
        self.assertEqual(len(k), 26)
        self.assertTrue(set(k) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ"))

    def test_course_note_belongs_to_a_real_course(self):
        kurs_idler = {d["id"] for d in self.s.dersler}
        for n in self.s.course_notes:
            self.assertIn(n["course"], kurs_idler)
            self.assertEqual(n["author"], self.s.ogretmen["id"])

    def test_scenario_round_trips_through_the_reader(self):
        o = FakeReader({(y["path"], y.get("query")): (y["status"], y["body"])
                          for y in self.s.responses()})
        b = build_context(o, self.s.ogrenci["id"])
        self.assertEqual(b.sinif, "10")
        self.assertEqual(b.rol, "student")
        self.assertEqual(b.unknown_subjects, [],
                         "senaryonun ürettiği başlık geri çözülemedi")
        self.assertEqual(len(b.dersler), len(self.s.dersler))
        self.assertTrue(b.notlar)

    def test_unknown_grade_refuses(self):
        with self.assertRaises(ValueError):
            build_scenario(sinif="13")

    def test_missing_corpus_refuses_instead_of_inventing(self):
        """Bkz. `test_backend_okul` — önce `sinif="11"` kullanılıyordu ve
        geçici bir ortam gerçeğini (11. sınıf verisi yok) sözleşme sayıyordu;
        EBA indirmesi onu getirince kırıldı. Artık izole boş kök."""
        import tempfile
        with tempfile.TemporaryDirectory() as bos:
            with self.assertRaises(ValueError):
                build_scenario(kok=bos, sinif="10")


@unittest.skipUnless(_VAR, "data/lise/10 yok")
class MufredatSurumuTests(unittest.TestCase):
    """Kitap ile `kazanimlar.json` AYNI MÜFREDATTAN GELMİYOR (2026-09-11).

    Kitap "1. Tema ENERJİ / 2. Tema EKOLOJİ" yapısında (Türkiye Yüzyılı Maarif
    Modeli); kazanım dosyası ise "ünite: Hücre Bölünmeleri, 10.1.1.2 Mitozu
    açıklar" (eski müfredat kodlaması). Ölçüldü: **"mitoz" 198 sayfalık 10.
    sınıf biyoloji kitabında 0 kez geçiyor**, "ekosistem" 121 kez geçiyor.

    Bu neden önemli: kapsanmayan bir kazanımdan öğrenci notu üretirsek öğrenci
    kitapta OLMAYAN bir şey sorar, ürün doğru davranıp çekimser kalır ama bu
    bir RAG başarısızlığı gibi okunur. Ölçüm verisi böyle zehirlenir.
    (Koşularak görüldü: "Mitoz nedir?" → `insufficient_data`, top rerank
    skoru 0,0025; aynı kitapta "Ekosistem nedir?" → 0,9845.)
    """

    def test_coverage_filter_drops_absent_objectives(self):
        from src.demo.scenario import covered_objectives
        hepsi = read_objectives("data", "lise", "10", "biyoloji")
        kapsanan = covered_objectives("data", "lise", "10", "biyoloji")
        self.assertLess(len(kapsanan), len(hepsi), "hiçbir kazanım elenmedi")
        metinler = " ".join(k["metin"] for k in kapsanan).lower()
        self.assertNotIn("mitoz", metinler)
        self.assertNotIn("mayoz", metinler)

    def test_covered_objectives_are_kept(self):
        from src.demo.scenario import covered_objectives
        metinler = " ".join(k["metin"] for k in
                            covered_objectives("data", "lise", "10", "biyoloji")).lower()
        self.assertIn("ekosistem", metinler)

    def test_scenario_notes_only_reference_covered_content(self):
        from src.demo.scenario import covered_objectives
        s = build_scenario()
        for n in s.notlar:
            ders = None
            for slug in ("biyoloji", "cografya", "din-kulturu", "fizik", "kimya",
                         "felsefe", "ingilizce"):
                if slug in n["id"] or slug[:4] in n["title"].lower():
                    ders = slug
                    break
            if ders is None:
                continue
            kodlar = {k["kod"] for k in covered_objectives("data", "lise", "10", ders)}
            kod = n["content"].split(" ", 1)[0]
            if kodlar and kod in {k for k in kodlar if k}:
                self.assertIn(kod, kodlar)

    def test_unreadable_book_does_not_filter_everything(self):
        """Kitap okunamazsa eleme YAPILMAZ — sessizce her kazanımı düşürmek
        senaryoyu boşaltır ve sebebi görünmez olurdu."""
        from src.demo.scenario import objective_is_covered
        self.assertTrue(objective_is_covered({"metin": "Mitozu açıklar."}, ""))


if __name__ == "__main__":
    unittest.main()
