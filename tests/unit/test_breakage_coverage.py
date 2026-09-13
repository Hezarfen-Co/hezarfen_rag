"""#74 / #M3-11 — kırılma kataloğu ↔ test haritasının DOĞRULANMASI.

Katalog (`tests/breakage_catalog.py`) her senaryoyu kapsayan testlerin tam
adlarını tutar. Bu dosya o adların GERÇEKTEN var olduğunu doğrular.

NEDEN GEREKLİ: harita elle yazılır. Bir test yeniden adlandırılır ya da
silinirse katalog sessizce yalan söylemeye devam eder ve "kapsam %81,6"
iddiası ölçümü değil, eski bir anıyı yansıtır. Kapı T-06 bu sayıya
dayandığı için haritanın çürümesi kapıyı geçersiz kılar.
"""
import functools
import unittest

from tests.breakage_catalog import (BY_ID, SCENARIOS, T06_MVP_THRESHOLD,
                                    coverage)


@functools.lru_cache(maxsize=1)
def _collected() -> tuple:
    """Depodaki tüm test kimlikleri (`dosya::Sinif::test`).

    pytest `--collect-only` ile toplamak DOĞRU sonucu verir ama bütün test
    modüllerini import ettiği için 177 s sürüyordu; hızlı suite'i tek başına
    yedi katına çıkarıyordu. Burada kaynak dosyalar AST ile okunur: import
    yok, model yüklemesi yok, saniyenin altında biter. Dinamik üretilen
    testleri göremez — katalog zaten elle yazılmış statik adlara işaret eder.
    """
    import ast
    import os
    ids = []
    for kok, _, dosyalar in os.walk("tests"):
        for ad in dosyalar:
            if not (ad.startswith("test_") and ad.endswith(".py")):
                continue
            yol = os.path.join(kok, ad)
            rel = os.path.relpath(yol, "tests").replace(os.sep, "/")
            try:
                agac = ast.parse(open(yol, encoding="utf-8").read())
            except SyntaxError:                       # noqa: PERF203
                continue
            for dugum in agac.body:
                if isinstance(dugum, ast.ClassDef):
                    for alt in dugum.body:
                        if (isinstance(alt, (ast.FunctionDef, ast.AsyncFunctionDef))
                                and alt.name.startswith("test")):
                            ids.append(f"{rel}::{dugum.name}::{alt.name}")
                elif (isinstance(dugum, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and dugum.name.startswith("test")):
                    ids.append(f"{rel}::{dugum.name}")
    return tuple(ids)


class CatalogIntegrityTests(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = [s.id for s in SCENARIOS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_scenario_has_a_title_and_expectation(self):
        for s in SCENARIOS:
            with self.subTest(s.id):
                self.assertTrue(s.title.strip())
                self.assertTrue(s.expected.strip())

    def test_uncovered_scenarios_explain_themselves(self):
        """Boş `covered_by` yeterli değil: NEYİN eksik olduğu yazılmalı,
        yoksa boşluk bir sonraki kişi için görünmez olur."""
        for s in SCENARIOS:
            if not s.covered:
                with self.subTest(s.id):
                    self.assertTrue(s.note.strip(),
                                    f"{s.id} kapsanmiyor ama neden yazilmamis")

    def test_catalog_matches_the_obsidian_numbering(self):
        """Benchmark §8.4'teki numaralandırma korunmalı; bir satır sessizce
        düşerse kapsam yüzdesi kendiliğinden yükselir."""
        beklenen = (["E-%02d" % i for i in range(1, 13)]
                    + ["E-%d" % i for i in range(20, 33)]
                    + ["E-%d" % i for i in range(40, 48)]
                    + ["E-%d" % i for i in range(60, 69)]
                    + ["E-%d" % i for i in range(80, 87)])
        self.assertEqual(sorted(BY_ID), sorted(beklenen))


class MapPointsAtRealTestsTests(unittest.TestCase):
    """HARİTA ÇÜRÜMESİNİ yakalayan test."""

    @classmethod
    def setUpClass(cls):
        cls.ids = _collected()
        if not cls.ids:
            raise unittest.SkipTest("test dosyasi bulunamadi")

    def test_every_reference_resolves(self):
        for s in SCENARIOS:
            for ref in s.covered_by:
                with self.subTest(scenario=s.id, ref=ref):
                    self.assertTrue(
                        any(t == ref or t.startswith(ref + "::") for t in self.ids),
                        f"{s.id} -> '{ref}' diye bir test YOK (yeniden "
                        f"adlandirildi ya da silindi)")

    def test_references_are_not_whole_directories(self):
        """Bir dizine işaret etmek kapsam sayısını şişirir."""
        for s in SCENARIOS:
            for ref in s.covered_by:
                with self.subTest(scenario=s.id, ref=ref):
                    self.assertTrue(ref.endswith(".py") or "::" in ref, ref)


class CoverageReportTests(unittest.TestCase):
    def test_coverage_is_reported_with_both_numbers(self):
        """Tek yüzde yanıltır: "kapsanıyor" ile "yeterince kapsanıyor" ayrı
        raporlanmalı."""
        t = coverage()["_toplam"]
        self.assertEqual(t["total"], len(SCENARIOS))
        self.assertEqual(t["covered"], t["full"] + t["partial"])
        self.assertLessEqual(t["full_ratio"], t["ratio"])

    def test_coverage_does_not_regress(self):
        """Bu bir KAPI DEĞİL, gerileme kilididir. Kapı T-06 kararını
        `src/eval/gates.py` verir; burada yalnız bugünkü ölçümün altına
        düşülmediği sabitlenir.

        ÖLÇÜLEN (2026-09-13): 40/49 bagli = %81,6 · 25/49 bosluksuz = %51,0
        """
        t = coverage()["_toplam"]
        self.assertGreaterEqual(t["covered"], 40,
                                "kirilma senaryosu kapsami GERILEDI")

    def test_the_threshold_is_data_not_a_verdict(self):
        """Araç kendini geçmiş ilan ETMEZ. Eşik burada yalnız bir sayıdır;
        kapı kararı ölçüm koşumunda verilir (#88)."""
        self.assertIsInstance(T06_MVP_THRESHOLD, float)
        self.assertNotIn("passed", coverage()["_toplam"])


if __name__ == "__main__":
    unittest.main()
