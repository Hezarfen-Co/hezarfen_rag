"""Faz 0.3b birim testleri — blok sınıflandırma + sütun-farkında okuma sırası.
Sentetik bloklarla (PDF gerekmez) → deterministik edge case'ler."""
import unittest

from src.ingest.pdf_parse import (Block, classify, order_blocks,
                                   HEADING, PARAGRAPH, LIST, CAPTION,
                                   HEADER, FOOTER, LABEL)

H = 800.0          # sayfa yüksekliği
BODY = 10.0        # gövde font medyanı


def c(text, size, bbox):
    return classify(text, size, bbox, H, BODY)


class ClassifyTests(unittest.TestCase):
    def test_heading_by_big_font(self):
        self.assertEqual(c("1.2.2. Genetik Mühendisliği", 13, (57, 53, 309, 66)), HEADING)

    def test_heading_by_section_marker_small_font(self):
        # "A) ..." font gövdeyle eşit ama bölüm işareti → heading
        self.assertEqual(c("A) Deoksiribonükleik Asit (DNA)", 11, (57, 54, 211, 68)), HEADING)

    def test_paragraph(self):
        t = "DNA; kalıtsal bilgiyi taşıyan, kalıtsal bilgiyi bir sonraki nesle aktaran moleküldür."
        self.assertEqual(c(t, 10, (57, 131, 397, 250)), PARAGRAPH)

    def test_list_bullets(self):
        self.assertEqual(c("• Birinci madde\n• İkinci madde", 10, (57, 300, 300, 340)), LIST)

    def test_list_numbered(self):
        self.assertEqual(c("1. Adım\n2. Adım\n3. Adım", 10, (57, 300, 300, 350)), LIST)

    def test_caption_gorsel(self):
        self.assertEqual(c("Görsel 1.9: Fosfodiester bağı", 8.5, (405, 281, 501, 295)), CAPTION)

    def test_caption_with_leading_marker(self):
        # kitap "W  Görsel..." öncü işaretini temizler
        self.assertEqual(c("W  Görsel 1.10: İkili sarmal", 8.5, (58, 679, 223, 692)), CAPTION)

    def test_header_top(self):
        self.assertEqual(c("1. BÖLÜM ● Nükleik Asitlerin Keşfi", 8, (334, 23, 508, 32)), HEADER)

    def test_footer_pageno(self):
        self.assertEqual(c("21", 10, (487, 747, 497, 760)), FOOTER)

    def test_label_short_diagram_noise(self):
        # diyagram etiketi: kısa + gövde-üstü değil
        self.assertEqual(c("3,4 nm", 11, (98, 474, 111, 486)), LABEL)

    def test_short_big_font_is_heading_not_label(self):
        # kısa ama büyük font → başlık (label değil); sıralama doğru mu
        self.assertEqual(c("Giriş", 15, (57, 60, 120, 78)), HEADING)


class OrderTests(unittest.TestCase):
    def _blk(self, x0, y0, x1, y1, kind=PARAGRAPH, text="x"):
        return Block(page=1, bbox=(x0, y0, x1, y1), text=text, block_no=0,
                     font_size=10.0, kind=kind)

    def test_single_column_y_order(self):
        b = [self._blk(50, 300, 200, 320), self._blk(50, 100, 200, 120),
             self._blk(50, 200, 200, 220)]
        out = order_blocks(b, page_width=300)
        ys = [x.bbox[1] for x in out]
        self.assertEqual(ys, [100, 200, 300])

    def test_two_column_left_before_right(self):
        # sol: y=100,300 ; sağ: y=50,200 → sol tümü sağdan önce (y küçük olsa bile)
        left = [self._blk(40, 100, 200, 120), self._blk(40, 300, 200, 320)]
        right = [self._blk(300, 50, 460, 70), self._blk(300, 200, 460, 220)]
        out = order_blocks(left + right, page_width=500)
        centers = [(x.bbox[0] + x.bbox[2]) / 2 for x in out]
        # ilk iki blok sol (<250), son iki blok sağ (>250)
        self.assertTrue(all(cx < 250 for cx in centers[:2]))
        self.assertTrue(all(cx > 250 for cx in centers[2:]))
        # sol kendi içinde y sıralı
        self.assertEqual([x.bbox[1] for x in out[:2]], [100, 300])

    def test_header_first_footer_last(self):
        b = [self._blk(50, 400, 200, 420, kind=FOOTER, text="12"),
             self._blk(50, 200, 200, 220, kind=PARAGRAPH),
             self._blk(50, 20, 200, 32, kind=HEADER, text="BÖLÜM")]
        out = order_blocks(b, page_width=300)
        self.assertEqual(out[0].kind, HEADER)
        self.assertEqual(out[-1].kind, FOOTER)

    def test_empty_no_crash(self):
        self.assertEqual(order_blocks([], page_width=300), [])


if __name__ == "__main__":
    unittest.main()
