"""Faz 0.3d integration testi — 12-bio görsel yoğunluk bulguları (gerçek veri)."""
import os
import unittest

from src.ingest.visuals import analyze_document, FIGURE, TEXT

BOOK = os.path.join("data", "lise", "12", "biyoloji", "kitap.pdf")


@unittest.skipUnless(os.path.exists(BOOK), f"veri yok: {BOOK}")
class VisualDensity12BioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prof = analyze_document(BOOK)

    def test_page_count(self):
        self.assertEqual(self.prof["page_count"], 187)

    def test_figure_heavy_share_plausible(self):
        s = self.prof["summary"]
        # ölçüm: ~50 sayfa figür-ağırlıklı (~%27). Geniş ama anlamlı aralık.
        self.assertGreaterEqual(s["figure_heavy"], 20)
        self.assertLessEqual(s["figure_heavy"], 90)
        self.assertGreater(s["figure_heavy_pct"], 0.10)

    def test_some_text_only_pages_exist(self):
        # düz metin yeten sayfalar var → ucuz flash ile işlenebilir
        self.assertGreater(self.prof["summary"]["low_visual"], 0)

    def test_avg_coverage_range(self):
        self.assertGreater(self.prof["summary"]["avg_image_coverage"], 0.05)
        self.assertLess(self.prof["summary"]["avg_image_coverage"], 0.8)

    def test_classes_cover_all_pages(self):
        s = self.prof["summary"]
        self.assertEqual(s["figure_heavy"] + s["mixed"] + s["low_visual"],
                         self.prof["page_count"])


if __name__ == "__main__":
    unittest.main()
