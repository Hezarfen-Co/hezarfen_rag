"""#85 (EXP-010/OPS-12) — istek izi: üretimde hiç üretilmiyordu.

grep ile doğrulanmıştı: `RequestTrace` yalnız `trace.py` ve
`observability/__init__.py`'de geçiyordu. `RagService.chat` `trace=`
geçirmiyordu → `Generator.answer(trace=None)` → **bütün `_tr()` çağrıları
no-op**. Sink yok, `request_id` yanıta dönmüyordu.

SONUÇ: **yeniden-oynatılabilirlik yok.** "Neden bu cevabı verdi?" sorusu
geriye dönük cevaplanamıyor; kalite regresyonu ve şikâyet incelemesi imkânsız.

KVKK SINIRI (#49 ile uyumlu): öğrencinin **sorgu metni ize yazılmaz** — yalnız
uzunluk + kısa hash. Metni yazmak, silinmesi gereken bir kişisel veriyi ikinci
bir yere kopyalamak demektir.
"""
import os
import tempfile
import unittest

from src.observability.trace import (RequestTrace, TRACE_PATH, read_traces,
                                     redact, write_trace)
from src.pricing import Usage


class RedactionTests(unittest.TestCase):
    def test_query_text_is_never_stored(self):
        gizli = "Ben cok kotuyum ve kendime zarar vermek istiyorum"
        d = redact(gizli)
        ham = str(d)
        self.assertNotIn("kotuyum", ham)
        self.assertNotIn("zarar", ham)
        self.assertEqual(d["len"], len(gizli))
        self.assertEqual(len(d["hash"]), 12)

    def test_same_text_same_hash(self):
        """Tekrar tespiti mümkün olmalı (aynı soru kaç kez soruldu)."""
        self.assertEqual(redact("ayni")["hash"], redact("ayni")["hash"])
        self.assertNotEqual(redact("a")["hash"], redact("b")["hash"])

    def test_none_is_safe(self):
        self.assertEqual(redact(None)["len"], 0)


class SinkTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.yol = os.path.join(self.d, "trace.jsonl")

    def _iz(self, **meta):
        t = RequestTrace()
        t.event("decision", **meta)
        return t

    def test_trace_is_written_and_read_back(self):
        self.assertTrue(write_trace(self._iz(stage="generate"), self.yol))
        kayitlar = read_traces(self.yol)
        self.assertEqual(len(kayitlar), 1)
        self.assertIn("request_id", kayitlar[0])
        self.assertIn("events", kayitlar[0])

    def test_disabled_by_default(self):
        """Veri minimizasyonu: yol verilmezse hiçbir şey yazılmaz."""
        self.assertEqual(TRACE_PATH, "")
        self.assertFalse(write_trace(self._iz(), ""))

    def test_failure_never_raises(self):
        """Telemetri hatası bir cevabı ASLA düşürmemeli."""
        try:
            ok = write_trace(self._iz(), "/dev/null/yok/trace.jsonl")
        except Exception as e:                   # pragma: no cover
            self.fail(f"telemetri hatasi istisna firlatti: {e!r}")
        self.assertFalse(ok)

    def test_sampling_drops_ordinary_traces(self):
        for _ in range(10):
            write_trace(self._iz(stage="generate"), self.yol,
                        sample=0.0, rng=lambda: 0.5)
        self.assertEqual(read_traces(self.yol), [])

    def test_abstained_traces_are_always_kept(self):
        """Örnekleme incelenmesi GEREKEN izleri atmamalı — izlenebilirlik en
        çok orada lazım."""
        write_trace(self._iz(abstained=True, reason="insufficient_data"),
                    self.yol, sample=0.0, rng=lambda: 0.5)
        self.assertEqual(len(read_traces(self.yol)), 1)

    def test_error_traces_are_always_kept(self):
        t = RequestTrace()
        t.event("error", kind="llm_unavailable")
        write_trace(t, self.yol, sample=0.0, rng=lambda: 0.5)
        self.assertEqual(len(read_traces(self.yol)), 1)

    def test_corrupt_line_does_not_lose_the_log(self):
        with open(self.yol, "w", encoding="utf-8") as fh:
            fh.write("{bozuk\n")
        write_trace(self._iz(), self.yol)
        self.assertEqual(len(read_traces(self.yol)), 1)


class SpanTests(unittest.TestCase):
    def test_span_records_duration(self):
        t = RequestTrace()
        with t.span("retrieval", top_k=20):
            pass
        olay = t.to_dict()["events"][-1]
        self.assertEqual(olay["name"], "retrieval")
        # `to_dict()` meta'yı DÜZLEŞTİRİR — ayrı bir "meta" anahtarı yoktur.
        self.assertIn("dur_ms", olay)

    def test_span_records_even_on_exception(self):
        t = RequestTrace()
        with self.assertRaises(ValueError):
            with t.span("rerank"):
                raise ValueError("patladi")
        self.assertEqual(t.to_dict()["events"][-1]["name"], "rerank")


class _Gen:
    """Trace'i gerçekten kullanan minimal generator."""

    def __init__(self):
        self.gorulen_trace = None

    def answer(self, query, *, trace=None, **kw):
        self.gorulen_trace = trace
        if trace is not None:
            trace.event("decision", stage="generate", abstained=False)

        class _A:
            text = "cevap [1]"
            citations = [{"n": 1, "chunk_id": "c1", "span_ids": ["s1"],
                          "pages": [3], "ders": "biyoloji"}]
            used_source_ids = ["c1"]
            invalid_citations = []
            abstained = False
            reason = ""
            cost_usd = 0.001
            cache_hit = False
            usage = Usage()
            n_sentences = 1
            n_cited_sentences = 1
        return _A()


class ServiceWiringTests(unittest.TestCase):
    """Asıl bulgu: servis `trace=` geçirmiyordu, yani iz HİÇ üretilmiyordu."""

    def setUp(self):
        from src.service.handler import RagService
        self.gen = _Gen()
        self.svc = RagService(self.gen)

    def test_service_passes_a_trace_to_the_generator(self):
        self.svc.chat({"query": "soru"})
        self.assertIsNotNone(self.gen.gorulen_trace,
                             "servis hala trace gecirmiyor")

    def test_request_id_is_returned_to_the_caller(self):
        out = self.svc.chat({"query": "soru"})
        self.assertIn("request_id", out)
        self.assertTrue(out["request_id"])

    def test_caller_supplied_request_id_is_used(self):
        """Uçtan uca izleme: backend kendi id'sini verirse o korunmalı."""
        out = self.svc.chat({"query": "soru", "request_id": "izlenebilir-1"})
        self.assertEqual(out["request_id"], "izlenebilir-1")

    def test_trace_records_the_decision_fields(self):
        d = tempfile.mkdtemp()
        yol = os.path.join(d, "t.jsonl")
        from unittest import mock
        from src.service import handler
        with mock.patch.object(handler, "write_trace",
                               lambda t, *a, **k: write_trace(t, yol)):
            self.svc.chat({"query": "soru"})
        kayitlar = read_traces(yol)
        self.assertTrue(kayitlar)
        adlar = {e["name"] for e in kayitlar[0]["events"]}
        self.assertIn("request", adlar)
        self.assertIn("response", adlar)

    def test_query_text_is_not_in_the_trace(self):
        d = tempfile.mkdtemp()
        yol = os.path.join(d, "t.jsonl")
        from unittest import mock
        from src.service import handler
        gizli = "kendime zarar vermek istiyorum cunku"
        with mock.patch.object(handler, "write_trace",
                               lambda t, *a, **k: write_trace(t, yol)):
            self.svc.chat({"query": gizli})
        ham = open(yol, encoding="utf-8").read()
        self.assertNotIn("zarar", ham)
        self.assertNotIn("cunku", ham)


if __name__ == "__main__":
    unittest.main()
