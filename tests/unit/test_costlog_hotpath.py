"""#84 (EXP-010/OPS-04) — maliyet defteri istek yolundan çıkarıldı.

ÖLÇÜLEN DURUM: `record()` her çağrıda kilit içinde **tüm `runs.jsonl`'ı okuyup
`Maliyet.md`'yi baştan yazıyordu** — her LLM cevabında, her guard çağrısında,
her özet parçasında. Bu depoda yeniden ölçüldü:

| satır | `record()` |
|---|---|
| 1.000 | 12,7 ms |
| 10.000 | 145,2 ms |
| 20.000 | 296,6 ms |
| **50.000** | **744,6 ms** |

Lineer büyüyor ve `flock` bunu süreçler arasında **serileştiriyor**.
Senaryo: 500 öğrenci × 5 soru/gün → 20 günde 50.000 satır → her cevaba +0,75 s.
"""
import json
import os
import tempfile
import time
import unittest
import warnings

from src import costlog
from src.pricing import Usage


def _dolgu(yol, n):
    with open(yol, "w", encoding="utf-8") as f:
        for i in range(1, n + 1):
            f.write(json.dumps({
                "run_id": f"R{i:05d}", "ts": "2026-09-12T00:00:00Z",
                "module": "chat", "model": "deepseek-chat", "tier": "peak",
                "items": 1, "config": {}, "usage": {"in_hit": 0, "in_miss": 10,
                "out": 5, "reasoning": 0}, "cost_usd": 0.0005,
                "unit_cost_usd": 0.0005, "quality": {}, "note": "x" * 40}) + "\n")


class HotPathTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.ledger = os.path.join(self.d, "runs.jsonl")
        self.md = os.path.join(self.d, "Maliyet.md")
        self.u = Usage(input_cache_hit=0, input_cache_miss=10, output=5)

    def _kaydet(self):
        return costlog.record(module="chat", model="deepseek-chat", usage=self.u,
                              ledger=self.ledger, maliyet=self.md)

    def test_render_is_not_in_the_request_path(self):
        """Varsayılan KAPALI: `record()` `Maliyet.md`'ye DOKUNMAZ."""
        self.assertFalse(costlog.RENDER_ON_RECORD)
        _dolgu(self.ledger, 100)
        self._kaydet()
        self.assertFalse(os.path.exists(self.md), "istek yolunda render yapıldı")

    def test_latency_does_not_grow_with_ledger_size(self):
        """Asıl kabul ölçütü: gecikme defter boyutundan BAĞIMSIZ olmalı."""
        sureler = {}
        for n in (1_000, 50_000):
            _dolgu(self.ledger, n)
            t = time.perf_counter()
            for _ in range(5):
                self._kaydet()
            sureler[n] = (time.perf_counter() - t) / 5
        self.assertLess(sureler[50_000], 0.05, "50k satırda record() hâlâ yavaş")
        # 50x büyük defterde 10 kattan fazla yavaşlamamalı (eskiden ~59 kat)
        self.assertLess(sureler[50_000], sureler[1_000] * 10 + 0.01)

    def test_ids_stay_monotonic_without_scanning_everything(self):
        _dolgu(self.ledger, 1_000)
        r1 = self._kaydet()
        r2 = self._kaydet()
        self.assertEqual(r1["run_id"], "R1001")
        self.assertEqual(r2["run_id"], "R1002")

    def test_broken_last_line_does_not_break_id_assignment(self):
        _dolgu(self.ledger, 10)
        with open(self.ledger, "a", encoding="utf-8") as f:
            f.write("{yarim satir\n")
        self.assertEqual(self._kaydet()["run_id"], "R0011")

    def test_empty_ledger_starts_at_one(self):
        self.assertEqual(self._kaydet()["run_id"], "R0001")

    def test_render_can_still_be_enabled_explicitly(self):
        from unittest import mock
        _dolgu(self.ledger, 10)
        with mock.patch.object(costlog, "RENDER_ON_RECORD", True):
            self._kaydet()
        self.assertTrue(os.path.exists(self.md))


class NeverBreakTheAnswerTests(unittest.TestCase):
    """Telemetri hatası cevabı ASLA düşürmemeli.

    Ölçülen somut örnek: `os.path.dirname(path)` dizinsiz yolda `""` döndürüyor,
    `makedirs("")` `FileNotFoundError` fırlatıyor ve bu `record()` içinden
    geldiği için **cevap üretildikten SONRA HTTP 500** oluyordu — para
    harcanmış, LLM çağrılmış, cevap hazır ve kullanıcıya hata gidiyor.
    """

    def test_dirless_path_does_not_raise(self):
        import os as _os
        onceki = _os.getcwd()
        d = tempfile.mkdtemp()
        try:
            _os.chdir(d)
            rec = costlog.record(module="chat", model="deepseek-chat",
                                 usage=Usage(), ledger="runs.jsonl",
                                 maliyet="Maliyet.md")
            self.assertEqual(rec["run_id"], "R0001")
        finally:
            _os.chdir(onceki)

    def test_record_safe_swallows_and_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            out = costlog.record_safe(module="chat", model="deepseek-chat",
                                      usage=Usage(),
                                      ledger="/dev/null/yok/runs.jsonl")
        self.assertIsNone(out)
        self.assertTrue(any(issubclass(x.category, RuntimeWarning) for x in w))

    def test_generators_default_to_the_safe_recorder(self):
        """Guard'da bu sarmalama zaten vardı; ÜRETİCİ yollarında yoktu."""
        import inspect
        from src.generate import generator, question_gen
        from src.summarize import summarizer
        for mod in (generator, question_gen, summarizer):
            with self.subTest(mod.__name__):
                self.assertIn("costlog.record_safe", inspect.getsource(mod))


class RenderCliTests(unittest.TestCase):
    def test_cli_renders_from_the_ledger(self):
        d = tempfile.mkdtemp()
        ledger = os.path.join(d, "runs.jsonl")
        out = os.path.join(d, "Maliyet.md")
        _dolgu(ledger, 20)
        self.assertEqual(costlog.main(["render", "--ledger", ledger, "--out", out]), 0)
        self.assertTrue(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
