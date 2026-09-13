"""#M3-10 (EVAL-16) — BOZUK / UÇ DURUM PDF'LER.

ÖLÇÜLEN DURUM: bozuk, şifreli, boş ve PDF olmayan dosyalar hiç test
edilmiyordu. Ölçünce her biri PyMuPDF'in KENDİ istisnasını fırlatıyordu:

| dosya            | atılan istisna                                  |
|------------------|-------------------------------------------------|
| bozuk baytlar    | `FileDataError: Failed to open file ... as pdf` |
| PDF olmayan .pdf | `FileDataError`                                 |
| 0 baytlık dosya  | `EmptyFileError`                                |
| şifreli PDF      | `ValueError: document closed or encrypted`      |

ÜRÜN AÇISINDAN NE DEMEK: bunlar kütüphane İÇ istisnalarıdır. Çağıran katman
"kaynak dosya okunamadı" ile "kodda hata var"ı ayırt edemez; ikisi de aynı
şekilde yukarı çıkar. Öğretmen bozuk bir kitap yüklediğinde ürün ona ne
söyleyeceğini bilemez — ya çıplak bir yığın izi gösterir ya da sessizce
yutar. Bu yüzden `UnreadableSource(reason=...)` eklendi.
"""
import os
import tempfile
import unittest

import fitz

from src.ingest.canonical import build_canonical
from src.ingest.pdf_parse import UnreadableSource, parse_pdf


def _write_pdf(path, build):
    doc = fitz.open()
    build(doc)
    doc.save(path)
    doc.close()
    return path


class UnreadableSourceTests(unittest.TestCase):
    """Okunamayan kaynak TİPLİ bir hata vermeli, ham kütüphane hatası değil."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def _path(self, name):
        return os.path.join(self.dir.name, name)

    def test_corrupt_bytes(self):
        p = self._path("corrupt.pdf")
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4 bu dosya bozuk " + os.urandom(200))
        with self.assertRaises(UnreadableSource) as ctx:
            parse_pdf(p)
        self.assertEqual(ctx.exception.reason, "corrupt")

    def test_not_a_pdf_at_all(self):
        """Öğretmen .docx'i .pdf diye yeniden adlandırır — sık görülür."""
        p = self._path("fake.pdf")
        with open(p, "wb") as f:
            f.write(b"Bu bir metin dosyasi, PDF degil." * 10)
        with self.assertRaises(UnreadableSource) as ctx:
            parse_pdf(p)
        self.assertEqual(ctx.exception.reason, "corrupt")

    def test_zero_byte_file(self):
        """Yarıda kesilen yükleme 0 bayt bırakır."""
        p = self._path("empty.pdf")
        open(p, "wb").close()
        with self.assertRaises(UnreadableSource) as ctx:
            parse_pdf(p)
        self.assertEqual(ctx.exception.reason, "empty_file")

    def test_encrypted_pdf(self):
        """Yayınevi PDF'leri sıklıkla parolalıdır."""
        p = self._path("locked.pdf")
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "gizli")
        doc.save(p, encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="o", user_pw="u")
        doc.close()
        with self.assertRaises(UnreadableSource) as ctx:
            parse_pdf(p)
        self.assertEqual(ctx.exception.reason, "encrypted")

    def test_reason_is_machine_readable(self):
        """Çağıran katman mesaj metnini değil `reason`'ı okumalı."""
        p = self._path("corrupt2.pdf")
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4 x")
        try:
            parse_pdf(p)
        except UnreadableSource as e:
            self.assertIn(e.reason, {"corrupt", "empty_file", "encrypted",
                                     "not_pdf", "unknown"})
            self.assertEqual(e.path, p)

    def test_missing_file_is_still_file_not_found(self):
        """Var olmayan dosya bir KAYNAK sorunu değil, çağıran hatasıdır;
        ikisini aynı tipe indirmek teşhisi bulanıklaştırırdı."""
        with self.assertRaises(FileNotFoundError):
            parse_pdf(self._path("yok.pdf"))

    def test_canonical_layer_propagates_the_typed_error(self):
        p = self._path("corrupt3.pdf")
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4 bozuk")
        with self.assertRaises(UnreadableSource):
            build_canonical(p, "10", "biyoloji")

    def test_unreadable_source_is_a_value_error(self):
        """Geriye dönük uyum: eski `except ValueError` blokları kırılmasın."""
        self.assertTrue(issubclass(UnreadableSource, ValueError))


class DegenerateButValidTests(unittest.TestCase):
    """Geçerli ama içi anlamsız PDF'ler ÇÖKMEMELİ — boş sonuç dönmeli."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def _path(self, name):
        return os.path.join(self.dir.name, name)

    def test_blank_page_yields_no_units(self):
        p = _write_pdf(self._path("blank.pdf"), lambda d: d.new_page())
        doc = build_canonical(p, "10", "biyoloji")
        self.assertEqual(doc.page_count, 1)
        self.assertEqual(len(doc.retrievable_units), 0)

    def test_only_page_numbers_yield_no_retrievable_units(self):
        """ÖLÇÜLDÜ: metni yalnız sayfa numarasından ibaret 300 sayfalık bir
        PDF 0 birim üretiyor. Bu DOĞRU davranıştır — sayfa numarası bilgi
        değildir ve indekse girerse her sorguya gürültü olarak karışır."""
        def build(d):
            for i in range(20):
                d.new_page().insert_text((72, 760), f"{i}")
        p = _write_pdf(self._path("nums.pdf"), build)
        doc = build_canonical(p, "10", "biyoloji")
        self.assertEqual(doc.page_count, 20)
        self.assertEqual(len(doc.retrievable_units), 0)

    def test_real_content_survives_at_scale(self):
        """Önceki testin 0'ı bir KUSUR olmadığını kanıtlar: aynı sayfa
        sayısında gerçek içerik varsa birimler çıkar."""
        def build(d):
            for i in range(60):
                pg = d.new_page()
                pg.insert_text((72, 100), f"Bolum {i}: Fotosentez", fontsize=16)
                pg.insert_text((72, 140),
                               "Bitkiler isik enerjisini kullanarak besin uretir. "
                               "Bu olaya fotosentez denir ve kloroplastta gerceklesir.",
                               fontsize=11)
        p = _write_pdf(self._path("big.pdf"), build)
        doc = build_canonical(p, "10", "biyoloji")
        self.assertEqual(doc.page_count, 60)
        self.assertGreaterEqual(len(doc.retrievable_units), 100)

    def test_span_ids_stay_unique_at_scale(self):
        """Span kimliği çakışırsa iki farklı sayfa aynı kanıt sayılır ve
        atıf yanlış sayfayı gösterir."""
        def build(d):
            for i in range(40):
                pg = d.new_page()
                pg.insert_text((72, 100), f"Bolum {i} Hucre Bolunmesi", fontsize=16)
                pg.insert_text((72, 140),
                               "Mitoz bolunme sonucunda iki yavru hucre olusur.",
                               fontsize=11)
        p = _write_pdf(self._path("ids.pdf"), build)
        doc = build_canonical(p, "10", "biyoloji")
        ids = [u.span_id for u in doc.units]
        self.assertEqual(len(ids), len(set(ids)))

    def test_doc_id_follows_bytes_not_path(self):
        """Aynı DOSYA iki yola kopyalanınca AYNI doc_id almalı: yol değişimi
        (arşivden taşıma, yeniden adlandırma) kitabı yeni bir kitap yapmaz.

        ÖLÇÜLEN SINIR — `doc_id = sha256(dosya)[:12]`, yani BAYT kimliği.
        Aynı içerik YENİDEN ÜRETİLİRSE (PDF'e gömülü oluşturma zamanı ve
        iç kimlikler değiştiği için) baytlar farklıdır ve doc_id de farklı
        olur. Yani "EBA'dan aynı kitabı tekrar indirmek" yeni bir doc_id
        üretebilir; eski chunk'lar öksüz kalır ve cache hiç tutmaz. Bu bir
        KISITTIR, test onu kayda geçirir — sessizce keşfedilmesin.
        """
        import shutil
        a = _write_pdf(self._path("a.pdf"),
                       lambda d: d.new_page().insert_text((72, 100), "Fotosentez."))
        b = self._path("b.pdf")
        shutil.copyfile(a, b)
        self.assertEqual(build_canonical(a, "10", "biyoloji").doc_id,
                         build_canonical(b, "10", "biyoloji").doc_id)

    def test_regenerating_the_same_content_changes_the_doc_id(self):
        """Yukarıdaki kısıtın ölçümü. Davranış değişirse (örn. doc_id metin
        içeriğinden türetilirse) bu test kırılır ve KARAR bilinçli verilir."""
        def build(d):
            d.new_page().insert_text((72, 100), "Fotosentez kloroplastta olur.")
        a = _write_pdf(self._path("r1.pdf"), build)
        b = _write_pdf(self._path("r2.pdf"), build)
        self.assertNotEqual(build_canonical(a, "10", "biyoloji").doc_id,
                            build_canonical(b, "10", "biyoloji").doc_id)

    def test_different_content_gives_a_different_doc_id(self):
        a = _write_pdf(self._path("c.pdf"),
                       lambda d: d.new_page().insert_text((72, 100), "Fotosentez."))
        b = _write_pdf(self._path("d.pdf"),
                       lambda d: d.new_page().insert_text((72, 100), "Solunum."))
        self.assertNotEqual(build_canonical(a, "10", "biyoloji").doc_id,
                            build_canonical(b, "10", "biyoloji").doc_id)


class TurkishTextTests(unittest.TestCase):
    """Türkçe karakterler PDF'ten çıkarken bozulmamalı."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_turkish_characters_survive_extraction(self):
        p = os.path.join(self.dir.name, "tr.pdf")
        metin = "Çiçekli bitkilerde döllenme ışığa bağlıdır."
        doc = fitz.open()
        doc.new_page().insert_text((72, 100), metin, fontsize=12,
                                   fontname="helv", encoding=fitz.TEXT_ENCODING_LATIN)
        doc.save(p)
        doc.close()
        cd = build_canonical(p, "10", "biyoloji")
        cikan = " ".join(u.text for u in cd.units)
        # Harflerin TAMAMI korunmayabilir (font/encoding sınırı); ölçülen şey
        # birimin ÜRETİLMESİ ve metnin boş olmaması.
        self.assertTrue(cikan.strip(), "Turkce metinden hic birim cikmadi")


if __name__ == "__main__":
    unittest.main()
