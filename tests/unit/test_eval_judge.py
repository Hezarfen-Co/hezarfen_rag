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
    def __init__(self, txt='{"ok":1}'): self.calls = []; self.txt = txt
    def chat(self, prompt, **k): self.calls.append(k); return _Chat(self.txt)


class _Schema:
    """DeepEval'in `schema=` ile verdiği pydantic modelinin yerine geçer:
    anahtar kelime argümanlarıyla kurulur ve alanları nitelik olur."""

    def __init__(self, **alanlar):
        self.__dict__.update(alanlar)


@unittest.skipUnless(_HAS_DEEPEVAL, "deepeval yok")
class JudgeModelTests(unittest.TestCase):
    def _model(self):
        m = DeepSeekJudgeModel()
        m._ds = _FakeDS()
        return m

    def test_schema_forces_json_mode(self):
        m = self._model()
        out = m.generate("değerlendir", schema=_Schema)
        self.assertEqual(m._ds.calls[-1].get("extra"),
                         {"response_format": {"type": "json_object"}})
        # KONTROL KOSUMUYLA BULUNDU (#72): burasi `schema` verilse de HER
        # KOSULDA metin donduruyordu. deepeval 2.9.3 o semanin NESNESINI
        # bekliyor; metin donunce her metrik `AttributeError: 'str' object
        # has no attribute 'truths'` ile patliyor ve hakem HIC calismiyordu.
        self.assertIsInstance(out, _Schema)
        self.assertEqual(out.ok, 1)

    def test_schema_parses_a_fenced_json_block(self):
        """Model JSON modunda bile ciktiyi kod blogu icine sarabiliyor."""
        m = self._model()
        m._ds = _FakeDS('```json\n{"ok": 2}\n```')
        self.assertEqual(m.generate("x", schema=_Schema).ok, 2)

    def test_schema_ignores_text_around_the_json(self):
        m = self._model()
        m._ds = _FakeDS('Iste sonuc: {"ok": 3} umarim yardimci olur.')
        self.assertEqual(m.generate("x", schema=_Schema).ok, 3)

    def test_unparsable_output_raises_instead_of_lying(self):
        """pass-bias YASAK: cozulemeyen cikti sessizce bos nesneye
        donusturulurse hakem "her sey yolunda" der."""
        m = self._model()
        m._ds = _FakeDS("hicbir json yok")
        with self.assertRaises(Exception):
            m.generate("x", schema=_Schema)

    def test_no_schema_no_extra(self):
        m = self._model()
        m.generate("düz istek")
        self.assertIsNone(m._ds.calls[-1].get("extra"))

    def test_usage_since_sums(self):
        m = self._model()
        cp = len(m.usages)
        m.generate("a", schema=_Schema)
        m.generate("b")
        u = m.usage_since(cp)
        self.assertEqual(u.output, 6)      # 3 + 3


if __name__ == "__main__":
    unittest.main()
