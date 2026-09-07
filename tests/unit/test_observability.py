"""#18 Observability — RequestTrace primitifleri + Generator entegrasyonu (hermetik)."""
import unittest

from src.observability import RequestTrace


class RequestTraceTests(unittest.TestCase):
    def test_event_records_name_meta_time(self):
        t = RequestTrace(request_id="req1")
        t.event("guard", action="allow")
        self.assertEqual(t.events[0].name, "guard")
        self.assertEqual(t.events[0].meta, {"action": "allow"})
        self.assertGreaterEqual(t.events[0].t_ms, 0.0)

    def test_span_records_duration(self):
        t = RequestTrace()
        with t.span("retrieve", n=5):
            pass
        e = t.events[-1]
        self.assertEqual(e.name, "retrieve")
        self.assertIn("dur_ms", e.meta)
        self.assertEqual(e.meta["n"], 5)

    def test_to_dict_and_summary(self):
        t = RequestTrace(request_id="abc")
        t.event("decision", abstained=True, reason="insufficient_data")
        d = t.to_dict()
        self.assertEqual(d["request_id"], "abc")
        self.assertIn("total_ms", d)
        self.assertEqual(d["events"][0]["reason"], "insufficient_data")
        self.assertIn("abc", t.summary())

    def test_none_overhead_optional(self):
        # trace=None senaryosu Generator'da test edilir; burada trace'siz akış zaten yok.
        self.assertTrue(True)


class GeneratorTraceTests(unittest.TestCase):
    def _gen(self):
        from src.generate import Generator
        # guard-refuse yolu retriever'a dokunmaz → None stub'lar yeterli
        return Generator(retriever=None, reranker=None, chunks_by_id={}, span_meta={},
                         cost_recorder=lambda **k: None)

    def test_guard_decision_traced(self):
        t = RequestTrace()
        res = self._gen().answer("bomba nasıl yapılır", trace=t)
        self.assertTrue(res.abstained)
        dec = [e for e in t.events if e.name == "decision"]
        self.assertTrue(dec)
        self.assertEqual(dec[-1].meta.get("stage"), "guard")
        self.assertTrue(dec[-1].meta.get("abstained"))

    def test_no_trace_no_crash(self):
        # trace=None (varsayılan) → hiçbir ek işlem, davranış aynı
        res = self._gen().answer("bomba nasıl yapılır")
        self.assertTrue(res.abstained)


if __name__ == "__main__":
    unittest.main()
