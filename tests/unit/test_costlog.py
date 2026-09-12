"""costlog testleri (AUDIT EXP-007 #28 + #29 kapsam-boşluğu). Hepsi offline (temp
dosya), gerçek Obsidian vault'a dokunmaz."""
import os
import tempfile
import unittest
import warnings

import src.costlog as costlog
from src.pricing import Usage


class CostlogTests(unittest.TestCase):
    def _paths(self, d):
        return os.path.join(d, "runs.jsonl"), os.path.join(d, "Maliyet.md")

    def test_sequential_ids_and_unit_cost(self):
        with tempfile.TemporaryDirectory() as d:
            L, M = self._paths(d)
            r1 = costlog.record("ozet", "deepseek-chat",
                                Usage(input_cache_miss=1000, output=500), items=10,
                                ledger=L, maliyet=M)
            r2 = costlog.record("chat", "deepseek-chat",
                                Usage(input_cache_miss=1000, output=500), items=1,
                                ledger=L, maliyet=M)
            self.assertEqual(r1["run_id"], "R0001")
            self.assertEqual(r2["run_id"], "R0002")          # #28: monoton, çakışmasız
            self.assertAlmostEqual(r1["unit_cost_usd"], round(r1["cost_usd"] / 10, 6))
            # SÖZLEŞME DEĞİŞTİ (#84, 2026-09-12): `record()` artık YALNIZ
            # append yapar. Eskiden her çağrıda `Maliyet.md` baştan yazılıyordu
            # ve bu, defter büyüdükçe her cevaba gecikme ekliyordu (ölçüldü:
            # 50.000 satırda 745 ms, lineer; `flock` süreçler arasında
            # serileştiriyor). Render artık `python -m src.costlog render`.
            self.assertTrue(os.path.exists(L))
            self.assertFalse(os.path.exists(M), "render istek yolunda kaldı")

    def test_unknown_model_does_not_crash_or_drop(self):
        with tempfile.TemporaryDirectory() as d:
            L, M = self._paths(d)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = costlog.record("ozet", "gpt-yok", Usage(output=1), ledger=L, maliyet=M)
            self.assertEqual(r["cost_usd"], 0.0)             # #R2: crash yok, 0 maliyet
            self.assertEqual(costlog._load(L)[0]["run_id"], "R0001")   # kayıt DÜŞMEDİ

    def test_render_atomic_no_tmp_leftover(self):
        with tempfile.TemporaryDirectory() as d:
            L, M = self._paths(d)
            costlog.record("ozet", "deepseek-chat", Usage(output=1), ledger=L, maliyet=M)
            leftovers = [f for f in os.listdir(d) if f.endswith(".tmp")]
            self.assertEqual(leftovers, [])                  # #28: temp temizlendi

    def test_corrupt_line_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            L, _ = self._paths(d)
            with open(L, "w", encoding="utf-8") as f:
                f.write('{"run_id":"R1","cost_usd":0.1}\n')
                f.write('YARIM {bozuk\n')
                f.write('{"run_id":"R2","cost_usd":0.2}\n')
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                rows = costlog._load(L)
            self.assertEqual([r["run_id"] for r in rows], ["R1", "R2"])

    def test_next_id_after_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            L, M = self._paths(d)
            with open(L, "w", encoding="utf-8") as f:
                f.write('{"run_id":"R0007"}\nBOZUK\n')
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = costlog.record("ozet", "deepseek-chat", Usage(output=1), ledger=L, maliyet=M)
            self.assertEqual(r["run_id"], "R0008")           # max+1, bozuk satıra rağmen


if __name__ == "__main__":
    unittest.main()
