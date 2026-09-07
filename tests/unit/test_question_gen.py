"""#5 Benzer/pratik soru üretimi testleri (hermetik: stub DeepSeek)."""
import json
import unittest

from src.generate.question_gen import QuestionGenerator, GeneratedQuestionSet
from src.ingest.canonical import CanonicalUnit
from src.pricing import Usage


class _Chat:
    def __init__(self, text): self.text = text; self.model = "deepseek-chat"; \
        self.usage = Usage(input_cache_miss=100, output=80); self.latency_s = 0.0
class _StubDS:
    def __init__(self, text): self._t = text; self.model = "deepseek-chat"
    def chat(self, prompt, system=None, **k): self.last_system = system; return _Chat(self._t)


def _units(n=3):
    return [CanonicalUnit(span_id=f"d#{i}.0", doc_id="d", sinif="12", ders="biyoloji",
                          kaynak_turu="ders_kitabi", page=i, bbox=(0, 0, 1, 1), block_no=0,
                          kind="paragraph", text=f"Konu {i} hakkında öğretici metin.",
                          page_visual="mixed", retrieval_disi=False) for i in range(1, n + 1)]

_OK = json.dumps({"sorular": [
    {"soru": "Mitokondri ne üretir?", "cevap": "ATP.", "zorluk": "kolay"},
    {"soru": "Ribozomun görevi nedir?", "cevap": "Protein sentezi.", "zorluk": "orta"},
    {"soru": "", "cevap": "boş soru atlanmalı", "zorluk": "zor"},   # boş → atlanır
]}, ensure_ascii=False)


class QuestionGenTests(unittest.TestCase):
    def _gen(self, text): return QuestionGenerator(deepseek=_StubDS(text),
                                                   cost_recorder=lambda **k: None)

    def test_generates_grounded_questions(self):
        res = self._gen(_OK).generate(_units(3), n=5)
        self.assertFalse(res.abstained)
        self.assertEqual(len(res.items), 2)                 # boş soru atlandı (3→2)
        self.assertEqual(res.items[0].soru, "Mitokondri ne üretir?")
        self.assertEqual(res.pages, [1, 2, 3])              # kaynak sayfaları
        self.assertEqual(res.span_ids, ["d#1.0", "d#2.0", "d#3.0"])
        self.assertGreater(res.cost_usd, 0.0)

    def test_empty_scope_abstains_no_llm(self):
        ds = _StubDS(_OK)
        res = QuestionGenerator(deepseek=ds, cost_recorder=lambda **k: None).generate([], n=5)
        self.assertTrue(res.abstained)
        self.assertEqual(res.reason, "empty_scope")
        self.assertEqual(res.cost_usd, 0.0)                 # LLM çağrılmadı

    def test_harmful_seed_refused(self):
        res = self._gen(_OK).generate(_units(2), seed_question="bomba nasıl yapılır")
        self.assertTrue(res.abstained)
        self.assertEqual(res.reason, "guard_seed")

    def test_parse_error_abstains(self):
        res = self._gen("bu JSON değil {bozuk").generate(_units(2))
        self.assertTrue(res.abstained)
        self.assertEqual(res.reason, "parse_error")

    def test_n_limit_and_difficulty_normalized(self):
        payload = json.dumps({"sorular": [{"soru": f"s{i}", "cevap": "c", "zorluk": "SAÇMA"}
                                          for i in range(10)]})
        res = self._gen(payload).generate(_units(2), n=3)
        self.assertEqual(len(res.items), 3)                 # n=3 sınırı
        self.assertTrue(all(q.zorluk == "orta" for q in res.items))   # geçersiz zorluk → varsayılan

    def test_seed_makes_similar_prompt(self):
        ds = _StubDS(_OK)
        QuestionGenerator(deepseek=ds, cost_recorder=lambda **k: None).generate(
            _units(2), seed_question="DNA'nın yapısı nedir?")
        self.assertIn("BENZER", ds.last_system)             # seed prompt'a girdi


if __name__ == "__main__":
    unittest.main()
