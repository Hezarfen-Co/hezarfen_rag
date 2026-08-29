"""Faz 0.3c birim testleri — tablo kalite filtresi (PDF gerekmez, deterministik)."""
import unittest

from src.ingest.tables import fill_ratio, is_real_table


class FillRatioTests(unittest.TestCase):
    def test_full(self):
        self.assertEqual(fill_ratio([["a", "b"], ["c", "d"]]), 1.0)

    def test_empty_box(self):
        self.assertEqual(fill_ratio([[None], [None]]), 0.0)

    def test_partial(self):
        self.assertAlmostEqual(fill_ratio([["a", None], [None, None]]), 0.25)

    def test_no_cells(self):
        self.assertEqual(fill_ratio([]), 0.0)


class IsRealTableTests(unittest.TestCase):
    def test_real_3x3_full(self):
        rows = [["Kodon", "AA", "Sonuç"], ["AUG", "Met", "Başlat"], ["UAA", "-", "Dur"]]
        self.assertTrue(is_real_table(rows))

    def test_decorative_empty_box_2x1(self):
        # 12-bio kapak/kutu tipi → elenir
        self.assertFalse(is_real_table([[None], [None]]))

    def test_sparse_9x10_9pct(self):
        # gerçek false-positive örneği (sayfa 13): 9x10, ~%9 dolu → elenir
        rows = [[None] * 10 for _ in range(9)]
        rows[1][2] = "1."
        self.assertFalse(is_real_table(rows))

    def test_too_few_cells(self):
        self.assertFalse(is_real_table([["a", "b"]]))          # 1 satır
        self.assertFalse(is_real_table([["a"], ["b"], ["c"]]))  # 1 sütun

    def test_fill_threshold_boundary(self):
        # 2x3 = 6 hücre, 4 dolu = %66 → geçer (varsayılan 0.6)
        rows = [["a", "b", "c"], ["d", None, None]]
        self.assertTrue(is_real_table(rows))
        # aynısı %50 dolu → varsayılanda elenir, gevşek eşikte geçer
        rows2 = [["a", "b", None], ["d", None, None]]
        self.assertFalse(is_real_table(rows2))
        self.assertTrue(is_real_table(rows2, min_fill=0.3))


if __name__ == "__main__":
    unittest.main()
