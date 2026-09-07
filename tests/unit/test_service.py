"""#2 RagService (transport-bağımsız handler) testleri — hermetik (stub bileşen)."""
import unittest

from src.service import RagService
from src.generate.generator import GroundedAnswer
from src.summarize.summarizer import GroundedSummary
from src.generate.question_gen import GeneratedQuestionSet, GeneratedQuestion
from src.ingest.canonical import CanonicalDoc, CanonicalUnit
from src.guard.roles import Role


class _GenStub:
    def __init__(self, ans): self.ans = ans; self.last_role = "UNSET"
    def answer(self, query, *, history=None, top_n=6, candidate_n=40, role_ctx="UNSET"):
        self.last_role = role_ctx
        return self.ans


class _SumStub:
    def __init__(self, res): self.res = res; self.last_units = None
    def summarize(self, units, *, scope_label=""): self.last_units = units; return self.res


class _QGStub:
    def __init__(self, res): self.res = res
    def generate(self, units, *, n=5, difficulty="orta", seed_question=None): return self.res


def _doc():
    u = [CanonicalUnit(span_id=f"d#{p}.0", doc_id="d", sinif="12", ders="biyoloji",
                       kaynak_turu="ders_kitabi", page=p, bbox=(0, 0, 1, 1), block_no=0,
                       kind="paragraph", text=f"metin {p}", page_visual="mixed",
                       retrieval_disi=False) for p in (10, 11)]
    return CanonicalDoc(source_path="d", doc_id="d", source_version="v", sinif="12",
                        ders="biyoloji", kaynak_turu="ders_kitabi", page_count=11, units=u)


_ANS = GroundedAnswer(text="Cevap [1].", citations=[{"n": 1, "chunk_id": "c1",
                      "span_ids": ["d#10.0"], "pages": [10], "ders": "biyoloji"}],
                      used_source_ids=["c1"], abstained=False, reason="", cost_usd=0.001)


class ChatTests(unittest.TestCase):
    def test_chat_maps_answer_and_role(self):
        g = _GenStub(_ANS)
        svc = RagService(g)
        out = svc.chat({"query": "DNA nedir", "role": {"role": "student", "sinif": "12",
                                                       "ders_list": ["biyoloji"]}})
        self.assertEqual(out["text"], "Cevap [1].")
        self.assertFalse(out["abstained"])
        self.assertEqual(out["citations"][0]["pages"], [10])
        self.assertEqual(g.last_role.role, Role.STUDENT)          # rol türetildi + geçti
        self.assertEqual(g.last_role.ders_list, ["biyoloji"])

    def test_empty_query_no_generator_call(self):
        g = _GenStub(_ANS)
        out = RagService(g).chat({"query": "   "})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "empty_query")
        self.assertEqual(g.last_role, "UNSET")                    # generator ÇAĞRILMADI

    def test_invalid_role_becomes_none(self):
        g = _GenStub(_ANS)
        RagService(g).chat({"query": "q", "role": {"role": "hacker"}})
        self.assertIsNone(g.last_role)                            # tanınmayan rol → None


class SummarizeTests(unittest.TestCase):
    def _svc(self):
        res = GroundedSummary(text="Özet [1].", citations=[{"n": 1, "span_ids": ["d#10.0"],
                              "pages": [10]}], scope_pages=[10, 11], cost_usd=0.02)
        return RagService(_GenStub(_ANS), doc=_doc(), summarizer=_SumStub(res), ders="biyoloji")

    def test_summarize_scope(self):
        out = self._svc().summarize({"scope": {"pages": [10, 11], "scope_label": "x"},
                                     "role": {"role": "student", "sinif": "12", "ders_list": ["biyoloji"]}})
        self.assertEqual(out["text"], "Özet [1].")
        self.assertEqual(out["scope_pages"], [10, 11])

    def test_summarize_empty_scope(self):
        out = self._svc().summarize({"scope": {}})
        self.assertTrue(out["abstained"]); self.assertEqual(out["reason"], "empty_scope")

    def test_summarize_role_denied_wrong_ders(self):
        out = self._svc().summarize({"scope": {"pages": [10]},
                                     "role": {"role": "student", "sinif": "12", "ders_list": ["kimya"]}})
        self.assertTrue(out["abstained"]); self.assertEqual(out["reason"], "role_denied")


class QuestionsTests(unittest.TestCase):
    def test_generate_questions(self):
        qres = GeneratedQuestionSet(items=[GeneratedQuestion("s1", "c1", "kolay")],
                                    span_ids=["d#10.0"], pages=[10], cost_usd=0.01)
        svc = RagService(_GenStub(_ANS), doc=_doc(), question_gen=_QGStub(qres), ders="biyoloji")
        out = svc.generate_questions({"scope": {"pages": [10]}, "n": 3})
        self.assertEqual(len(out["items"]), 1)
        self.assertEqual(out["items"][0]["soru"], "s1")
        self.assertEqual(out["pages"], [10])


if __name__ == "__main__":
    unittest.main()
