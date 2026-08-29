"""Faz 0.3d birim testleri — görsel kaplama (union) + sınıf + bölge render.
Sentetik dikdörtgen/PDF ile deterministik (büyük veri gerekmez)."""
import unittest

import fitz

from src.ingest.visuals import _grid_coverage, _classify, render_region, FIGURE, MIXED, TEXT

W, H = 400.0, 560.0


class CoverageTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_grid_coverage([], W, H), 0.0)

    def test_full_page(self):
        self.assertAlmostEqual(_grid_coverage([(0, 0, W, H)], W, H), 1.0, places=2)

    def test_overlap_is_union_not_sum(self):
        # Aynı dikdörtgen iki kez → union %100'ü AŞMAZ (alan-toplamı hatasının önlenmesi)
        cov = _grid_coverage([(0, 0, W, H), (0, 0, W, H)], W, H)
        self.assertLessEqual(cov, 1.0)
        self.assertAlmostEqual(cov, 1.0, places=2)

    def test_half_page(self):
        self.assertAlmostEqual(_grid_coverage([(0, 0, W / 2, H)], W, H), 0.5, delta=0.05)

    def test_two_disjoint_halves_union(self):
        cov = _grid_coverage([(0, 0, W / 2, H), (W / 2, 0, W, H)], W, H)
        self.assertAlmostEqual(cov, 1.0, places=2)

    def test_degenerate_rect_ignored(self):
        self.assertEqual(_grid_coverage([(10, 10, 10, 50)], W, H), 0.0)


class ClassifyTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(_classify(0.55), FIGURE)   # ≥0.40
        self.assertEqual(_classify(0.40), FIGURE)
        self.assertEqual(_classify(0.20), MIXED)    # 0.10–0.40
        self.assertEqual(_classify(0.10), MIXED)
        self.assertEqual(_classify(0.05), TEXT)     # <0.10


class RenderTests(unittest.TestCase):
    def test_render_region_returns_png(self):
        # sentetik 1 sayfalık PDF → bölge render → PNG imzası
        doc = fitz.open()
        page = doc.new_page(width=W, height=H)
        page.insert_text((50, 100), "Test")
        png = render_region(page, (0, 0, 200, 200))
        doc.close()
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"), "PNG imzası yok")
        self.assertGreater(len(png), 100)


if __name__ == "__main__":
    unittest.main()
