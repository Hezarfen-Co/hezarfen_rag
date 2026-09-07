"""eval/judge testleri (AUDIT EXP-007 #29 — judge 0-test'ti). Ağ yok: sahte DeepSeek.
DeepEval import'u gerektiğinden yoksa atla."""
import unittest

try:
    from src.eval.judge import DeepSeekJudgeModel
    _HAS_DEEPEVAL = True
except Exception:
    _HAS_DEEPEVAL = False

from src.pricing import Usage


class _Chat:
    def __init__(self, txt): self.text = txt; self.usage = Usage(output=3); \
        self.model = "deepseek-chat"; self.latency_s = 0.0
class _FakeDS:
    def __init__(self): self.calls = []
    def chat(self, prompt, **k): self.calls.append(k); return _Chat('{"ok":1}')


@unittest.skipUnless(_HAS_DEEPEVAL, "deepeval yok")
class JudgeModelTests(unittest.TestCase):
    def _model(self):
        m = DeepSeekJudgeModel()
        m._ds = _FakeDS()
        return m

    def test_schema_forces_json_mode(self):
        m = self._model()
        out = m.generate("değerlendir", schema={"a": 1})
        self.assertEqual(out, '{"ok":1}')
        self.assertEqual(m._ds.calls[-1].get("extra"),
                         {"response_format": {"type": "json_object"}})

    def test_no_schema_no_extra(self):
        m = self._model()
        m.generate("düz istek")
        self.assertIsNone(m._ds.calls[-1].get("extra"))

    def test_usage_since_sums(self):
        m = self._model()
        cp = len(m.usages)
        m.generate("a", schema={"x": 1})
        m.generate("b")
        u = m.usage_since(cp)
        self.assertEqual(u.output, 6)      # 3 + 3


if __name__ == "__main__":
    unittest.main()
