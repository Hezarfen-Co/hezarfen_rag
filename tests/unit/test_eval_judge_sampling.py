"""M0-5 (#37) — tabakalı hakem örneklemesi testleri.

NEDEN (EXP-010/EVAL-04): eski kural "critical + temsil edilmeyen ünitede ilk
item" idi. Ölçülen sonuç bio v1.1'de judge yalnız **22/133** cevaplanabilir item
(%16,5) alıyordu ve kategori dağılımı `zor` 12 + `multi_turn` 10 idi — yani
**`kolay` (46) ve `orta` (53) item'ların TAMAMI hakemsizdi**. Kullanıcıların en
sık soracağı soru sınıfında üretim kalitesi hiç ölçülmemişti.

Daha kötüsü: kimya/fizik setlerinde `critical & cevapla` item olmadığı için
**judge n=0** kalıyordu → EXP-005/EXP-008'in non-bio "kalite" iddiasında
faithfulness/correctness hiç ölçülmemişti.

Bu testler yeni davranışı GERÇEK golden set'ler üzerinde de sabitler.
"""
import json
import os
import unittest
from unittest import mock

from src.eval import runner as R


def _it(item_id, kategori="orta", senaryo=None, unite="U1",
        critical=False, beklenen="cevapla"):
    d = {"id": item_id, "kategori": kategori, "unite": unite,
         "critical": critical, "beklenen_davranis": beklenen}
    if senaryo:
        d["senaryo"] = senaryo
    return d


class StratifiedSamplingTests(unittest.TestCase):
    def test_all_critical_items_are_mandatory(self):
        items = [_it("c1", critical=True), _it("c2", critical=True),
                 _it("n1"), _it("n2")]
        ids = R._select_judge_ids(items, sample_n=2)
        self.assertIn("c1", ids)
        self.assertIn("c2", ids)

    def test_every_category_gets_at_least_one(self):
        """EVAL-04'ün çekirdeği: kolay/orta artık dışarıda kalamaz."""
        items = ([_it(f"k{i}", kategori="kolay") for i in range(20)]
                 + [_it(f"o{i}", kategori="orta") for i in range(20)]
                 + [_it("z1", kategori="zor", critical=True)])
        ids = R._select_judge_ids(items, sample_n=5)
        cats = {it["kategori"] for it in items if it["id"] in ids}
        self.assertEqual(cats, {"kolay", "orta", "zor"})

    def test_every_unit_gets_at_least_one(self):
        items = [_it("a", unite="U1", critical=True), _it("b", unite="U2"),
                 _it("c", unite="U3")]
        ids = R._select_judge_ids(items, sample_n=1)
        units = {it["unite"] for it in items if it["id"] in ids}
        self.assertEqual(units, {"U1", "U2", "U3"})

    def test_senaryo_is_part_of_the_stratum(self):
        items = ([_it(f"d{i}", senaryo="direct") for i in range(10)]
                 + [_it(f"m{i}", senaryo="multi_hop") for i in range(10)]
                 + [_it(f"v{i}", senaryo="variant") for i in range(10)])
        ids = R._select_judge_ids(items, sample_n=3)
        sen = {it.get("senaryo") for it in items if it["id"] in ids}
        self.assertEqual(sen, {"direct", "multi_hop", "variant"})

    def test_only_answerable_items_are_sampled(self):
        items = [_it("a"), _it("r1", beklenen="red", critical=True),
                 _it("e1", beklenen="cekimser", critical=True)]
        ids = R._select_judge_ids(items, sample_n=10)
        self.assertEqual(ids, {"a"})

    def test_deterministic_for_fixed_seed(self):
        items = [_it(f"i{i}", kategori=("kolay" if i % 2 else "orta"))
                 for i in range(40)]
        self.assertEqual(R._select_judge_ids(items, sample_n=12),
                         R._select_judge_ids(items, sample_n=12))

    def test_different_seed_gives_different_sample(self):
        items = [_it(f"i{i}") for i in range(40)]
        a = R._select_judge_ids(items, sample_n=10, seed=1)
        b = R._select_judge_ids(items, sample_n=10, seed=2)
        self.assertNotEqual(a, b)

    def test_sample_size_is_respected_approximately(self):
        items = [_it(f"i{i}", kategori=("kolay" if i % 3 else "orta"))
                 for i in range(100)]
        ids = R._select_judge_ids(items, sample_n=25)
        # tabaka/ünite garantileri hedefi biraz aşabilir; ama 2 katına çıkmamalı
        self.assertGreaterEqual(len(ids), 25)
        self.assertLess(len(ids), 50)

    def test_sample_larger_than_pool(self):
        items = [_it("a"), _it("b")]
        self.assertEqual(R._select_judge_ids(items, sample_n=99), {"a", "b"})


class FrozenJudgeSetTests(unittest.TestCase):
    def test_frozen_ids_loaded_from_file(self):
        """EVAL-04: sürümler arası kıyas AYNI örnek üzerinde yapılmalı."""
        import tempfile
        items = [_it("a"), _it("b"), _it("c")]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            json.dump(["a", "c"], fh)
            path = fh.name
        try:
            with mock.patch.object(R, "JUDGE_IDS_PATH", path):
                self.assertEqual(R._select_judge_ids(items), {"a", "c"})
        finally:
            os.unlink(path)

    def test_frozen_ids_missing_from_set_are_dropped_with_warning(self):
        import tempfile
        items = [_it("a")]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            json.dump(["a", "yok1", "yok2"], fh)
            path = fh.name
        try:
            with mock.patch.object(R, "JUDGE_IDS_PATH", path):
                self.assertEqual(R._select_judge_ids(items), {"a"})
        finally:
            os.unlink(path)


class CompositionReportTests(unittest.TestCase):
    def test_composition_exposes_coverage_and_breakdown(self):
        items = ([_it(f"k{i}", kategori="kolay") for i in range(10)]
                 + [_it(f"z{i}", kategori="zor", critical=True) for i in range(3)])
        ids = R._select_judge_ids(items, sample_n=6)
        comp = R._judge_composition(items, ids)
        self.assertEqual(comp["n_answerable"], 13)
        self.assertEqual(comp["n_selected"], len(ids))
        self.assertAlmostEqual(comp["coverage"], len(ids) / 13)
        self.assertIn("kolay", comp["by_kategori"])
        self.assertIn("zor", comp["by_kategori"])
        self.assertEqual(comp["kategoriler_hakemsiz"], [])

    def test_composition_flags_uncovered_categories(self):
        items = [_it("a", kategori="kolay"), _it("b", kategori="zor")]
        comp = R._judge_composition(items, {"a"})
        self.assertEqual(comp["kategoriler_hakemsiz"], ["zor"])


class RealGoldenSetTests(unittest.TestCase):
    """Gerçek setler üzerinde EVAL-04'ün kapandığını sabitler."""

    def _items(self, name):
        path = os.path.join("tests", "golden", name)
        if not os.path.exists(path):
            self.skipTest(f"{name} yok")
        return json.load(open(path, encoding="utf-8"))["items"]

    def test_bio_covers_kolay_and_orta_now(self):
        items = self._items("golden_12bio_v1.json")
        comp = R._judge_composition(items, R._select_judge_ids(items))
        self.assertIn("kolay", comp["by_kategori"])   # eskiden 0'di
        self.assertIn("orta", comp["by_kategori"])    # eskiden 0'di
        self.assertGreater(comp["coverage"], 0.25)    # eskiden %16.5
        self.assertEqual(comp["kategoriler_hakemsiz"], [])

    def test_non_bio_sets_no_longer_get_zero_judges(self):
        """EXP-005/008'in non-bio kalite iddiasi bu yuzden olculmemisti."""
        for name in ("golden_12kimya_v1.json", "golden_12fizik_v1.json"):
            items = self._items(name)
            comp = R._judge_composition(items, R._select_judge_ids(items))
            with self.subTest(name):
                self.assertGreater(comp["n_selected"], 0)


if __name__ == "__main__":
    unittest.main()
