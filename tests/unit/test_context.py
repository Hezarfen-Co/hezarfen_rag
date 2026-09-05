"""Faz birim testleri — context packing (token bütçe + lost-in-the-middle). LLM gerekmez."""
import unittest
from dataclasses import dataclass, field

from src.context import apply_token_budget, reorder_lost_in_middle, pack_contexts


@dataclass
class _Ctx:
    chunk_id: str
    text: str
    score: float = 1.0
    parent_text: str | None = None


def _mk(n, words_each=100):
    # her context ~words_each kelime -> approx_tokens ile ölçülebilir token
    return [_Ctx(f"c{i}", " ".join(["kelime"] * words_each), score=1.0 - i * 0.1)
            for i in range(n)]


class TokenBudgetTests(unittest.TestCase):
    def test_budget_drops_low_score_tail(self):
        ctxs = _mk(5, words_each=100)   # her biri ~130 token (100 kelime * 1.3)
        kept = apply_token_budget(ctxs, max_tokens=300)   # ~2 context sığar
        self.assertLess(len(kept), 5)
        self.assertGreaterEqual(len(kept), 1)
        self.assertEqual(kept[0].chunk_id, "c0")          # en yüksek skor korunur

    def test_always_keeps_at_least_one(self):
        ctxs = _mk(3, words_each=5000)   # her biri bütçeden büyük
        kept = apply_token_budget(ctxs, max_tokens=10)
        self.assertEqual(len(kept), 1)                    # ilk context her zaman kalır
        self.assertEqual(kept[0].chunk_id, "c0")

    def test_all_fit_under_budget(self):
        ctxs = _mk(3, words_each=10)
        kept = apply_token_budget(ctxs, max_tokens=100000)
        self.assertEqual(len(kept), 3)

    def test_empty(self):
        self.assertEqual(apply_token_budget([], 100), [])


class LostInMiddleTests(unittest.TestCase):
    def test_strong_at_ends_weak_in_middle(self):
        ctxs = _mk(5)   # c0 en güçlü, c4 en zayıf
        out = [c.chunk_id for c in reorder_lost_in_middle(ctxs)]
        self.assertEqual(out, ["c0", "c2", "c4", "c3", "c1"])
        self.assertEqual(out[0], "c0")                    # en güçlü başta
        self.assertEqual(out[-1], "c1")                   # 2. güçlü sonda
        self.assertEqual(out[len(out) // 2], "c4")        # en zayıf ortada

    def test_two_or_fewer_unchanged(self):
        ctxs = _mk(2)
        self.assertEqual([c.chunk_id for c in reorder_lost_in_middle(ctxs)], ["c0", "c1"])
        self.assertEqual(reorder_lost_in_middle([]), [])

    def test_pack_combines_budget_and_reorder(self):
        ctxs = _mk(5, words_each=10)     # hepsi sığar
        out = [c.chunk_id for c in pack_contexts(ctxs, max_tokens=100000, reorder=True)]
        self.assertEqual(out, ["c0", "c2", "c4", "c3", "c1"])

    def test_pack_no_reorder(self):
        ctxs = _mk(4, words_each=10)
        out = [c.chunk_id for c in pack_contexts(ctxs, max_tokens=100000, reorder=False)]
        self.assertEqual(out, ["c0", "c1", "c2", "c3"])

    def test_parent_text_counts_toward_budget(self):
        # parent_text token maliyetine dahil edilmeli
        c = _Ctx("c0", "kısa", score=1.0, parent_text=" ".join(["uzun"] * 5000))
        kept = apply_token_budget([c, _Ctx("c1", "kısa2", 0.9)], max_tokens=50)
        self.assertEqual(len(kept), 1)   # c0'ın parent'ı bütçeyi doldurur


if __name__ == "__main__":
    unittest.main()
