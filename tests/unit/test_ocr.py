"""Faz 0.8 birim testleri — OCR fallback (hermetik: gerçek tesseract gerektirmez).

Zarif degradasyon + saf yardımcılar (_page_needs_ocr, _ocr_blocks) + dil çözümü
(_resolve_lang) monkeypatch ile test edilir; gerçek OCR motoru DEMO'da (scratchpad)
ayrıca doğrulanır."""
import os
import unittest

from src.ingest import ocr as ocr_mod
from src.ingest.pdf_parse import Block, PARAGRAPH, HEADING, _page_needs_ocr, _ocr_blocks


def _b(text, block_no, kind=PARAGRAPH):
    return Block(page=1, bbox=(0, 0, 400, 560), text=text, block_no=block_no, kind=kind)


class PageNeedsOcrTests(unittest.TestCase):
    def test_empty_text_with_image_needs_ocr(self):
        # gövde metni yok + görüntü var → OCR adayı
        self.assertTrue(_page_needs_ocr([], has_images=True, min_chars=20))

    def test_empty_text_no_image_skips(self):
        # görüntüsüz boş sayfa (ayraç) → OCR YOK (uydurulacak metin yok)
        self.assertFalse(_page_needs_ocr([], has_images=False, min_chars=20))

    def test_healthy_text_layer_skips(self):
        blocks = [_b("Bu sayfada bol miktarda öğretici gövde metni bulunuyor.", 0)]
        self.assertFalse(_page_needs_ocr(blocks, has_images=True, min_chars=20))

    def test_only_label_noise_still_needs_ocr(self):
        # yalnız kısa etiket (is_body=False değil ama < min_chars) + görüntü → OCR
        blocks = [_b("3,4 nm", 0)]  # 6 kar < 20
        self.assertTrue(_page_needs_ocr(blocks, has_images=True, min_chars=20))


class OcrBlocksTests(unittest.TestCase):
    def test_splits_paragraphs(self):
        text = "Birinci paragraf.\n\nİkinci paragraf.\n\n  \n\nÜçüncü."
        blocks = _ocr_blocks(text, page_no=5, width=400, height=560)
        self.assertEqual([b.text for b in blocks],
                         ["Birinci paragraf.", "İkinci paragraf.", "Üçüncü."])
        self.assertTrue(all(b.ocr for b in blocks))            # provenance
        self.assertTrue(all(b.is_body for b in blocks))        # indekslenir
        self.assertTrue(all(b.page == 5 for b in blocks))
        self.assertEqual([b.block_no for b in blocks], [9000, 9001, 9002])
        self.assertTrue(all(b.bbox == (0.0, 0.0, 400, 560) for b in blocks))

    def test_empty_text_no_blocks(self):
        self.assertEqual(_ocr_blocks("", 1, 400, 560), [])
        self.assertEqual(_ocr_blocks("   \n\n  ", 1, 400, 560), [])


class GracefulDegradationTests(unittest.TestCase):
    def test_unavailable_when_pytesseract_missing(self):
        orig = ocr_mod._pt
        ocr_mod._pt = lambda: None
        try:
            self.assertFalse(ocr_mod.ocr_available("tur"))
            self.assertEqual(ocr_mod.ocr_page(None, lang="tur"), "")  # page'e hiç dokunmaz
        finally:
            ocr_mod._pt = orig

    def test_ocr_page_swallows_errors(self):
        # _pt sahte döner ama render/OCR patlar → "" (çökme yok)
        class _Boom:
            class pytesseract:
                tesseract_cmd = ""
            def image_to_string(self, *a, **k):
                raise RuntimeError("motor patladı")
        orig = ocr_mod._pt
        ocr_mod._pt = lambda: _Boom()
        try:
            class _FakePage:
                def get_pixmap(self, *a, **k):
                    raise RuntimeError("render patladı")
            self.assertEqual(ocr_mod.ocr_page(_FakePage(), lang="tur"), "")
        finally:
            ocr_mod._pt = orig


class ResolveLangTests(unittest.TestCase):
    def test_local_tur_preferred(self):
        # models/tessdata/tur.traineddata varsa yerel dizin + tur seçilir
        if ocr_mod._local_tessdata("tur") is None:
            self.skipTest("yerel tur.traineddata yok")
        lang, tessdata_dir = ocr_mod._resolve_lang(object(), "tur")
        self.assertEqual(lang, "tur")
        # dizin döner (TESSDATA_PREFIX'e konur); tırnaklı --tessdata-dir DEĞİL
        self.assertTrue(tessdata_dir.endswith("tessdata"))
        self.assertTrue(os.path.isdir(tessdata_dir))

    def test_falls_back_to_eng_when_lang_absent(self):
        class _FakePt:
            def get_languages(self, config=""):
                return ["eng", "osd"]
        # yerel veride olmayan bir dil iste → eng'e düş, dizin yok
        lang, tessdata_dir = ocr_mod._resolve_lang(_FakePt(), "deu")
        self.assertEqual(lang, "eng")
        self.assertEqual(tessdata_dir, "")


if __name__ == "__main__":
    unittest.main()
