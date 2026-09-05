"""Faz 5 (#23) birim testleri — VLM captioning (hermetik: gerçek API gerektirmez).

Sağlayıcı-bağımsız istemci + zarif degradasyon + saf yardımcılar
(target_visual_pages, merge_visual_units). Gerçek VLM çağrısı DEMO'da (key gelince)."""
import unittest

from src.providers.vlm import VLMCaptioner
from src.ingest.canonical import CanonicalUnit
from src.ingest.visual_caption import (VISUAL_KIND, target_visual_pages,
                                       merge_visual_units, caption_visual_units)


def _u(page, block_no, kind="paragraph", text="metin"):
    return CanonicalUnit(
        span_id=f"doc#{page}.{block_no}", doc_id="doc", sinif="12", ders="biyoloji",
        kaynak_turu="ders_kitabi", page=page, bbox=(0, 0, 400, 560), block_no=block_no,
        kind=kind, text=text, page_visual="mixed", retrieval_disi=False)


class AvailabilityTests(unittest.TestCase):
    def test_unavailable_without_config(self):
        c = VLMCaptioner(model=None, base_url=None, api_key=None)
        self.assertFalse(c.available())
        self.assertEqual(c.caption(b"\x89PNG..."), "")            # HTTP yapmaz
        r = c.caption_with_usage(b"\x89PNG...")
        self.assertEqual(r.text, "")
        self.assertEqual(r.usage.total, 0)            # boş Usage

    def test_available_with_full_config(self):
        c = VLMCaptioner(model="m", base_url="https://x/v1", api_key="k")
        self.assertTrue(c.available())

    def test_partial_config_unavailable(self):
        self.assertFalse(VLMCaptioner(model="m", base_url="https://x/v1", api_key=None).available())
        self.assertFalse(VLMCaptioner(model=None, base_url="https://x/v1", api_key="k").available())


class TargetPagesTests(unittest.TestCase):
    def test_only_figure_heavy(self):
        pv = {1: "low_visual", 2: "figure_heavy", 3: "mixed", 4: "figure_heavy"}
        self.assertEqual(target_visual_pages(pv), [2, 4])

    def test_custom_classes(self):
        pv = {1: "low_visual", 2: "figure_heavy", 3: "mixed"}
        self.assertEqual(target_visual_pages(pv, ("figure_heavy", "mixed")), [2, 3])


class MergeTests(unittest.TestCase):
    def test_inserts_after_page_last_text_unit(self):
        text = [_u(1, 0), _u(1, 1), _u(2, 0)]
        vis = [_u(1, 8000, VISUAL_KIND, "gorsel1")]
        merged = merge_visual_units(text, vis)
        # sayfa 1'in son metin biriminden (block 1) SONRA, sayfa 2'den ÖNCE
        self.assertEqual([(u.page, u.block_no) for u in merged],
                         [(1, 0), (1, 1), (1, 8000), (2, 0)])

    def test_textless_visual_page_appended_end(self):
        text = [_u(1, 0)]
        vis = [_u(5, 8000, VISUAL_KIND, "gorsel5")]   # sayfa 5'te metin yok
        merged = merge_visual_units(text, vis)
        self.assertEqual([(u.page, u.block_no) for u in merged], [(1, 0), (5, 8000)])

    def test_empty_visuals_unchanged(self):
        text = [_u(1, 0), _u(1, 1)]
        self.assertIs(merge_visual_units(text, []), text)


class GracefulCaptionPassTests(unittest.TestCase):
    def test_unavailable_captioner_no_units(self):
        # captioner None → boş; kullanılamaz captioner → boş (dosyaya bile dokunmaz)
        self.assertEqual(caption_visual_units(
            "yok.pdf", doc_id="d", sinif="12", ders="biyoloji", kaynak_turu="ders_kitabi",
            page_visual={1: "figure_heavy"}, captioner=None), [])
        c = VLMCaptioner(model=None, base_url=None, api_key=None)
        self.assertEqual(caption_visual_units(
            "yok.pdf", doc_id="d", sinif="12", ders="biyoloji", kaynak_turu="ders_kitabi",
            page_visual={1: "figure_heavy"}, captioner=c), [])


if __name__ == "__main__":
    unittest.main()
