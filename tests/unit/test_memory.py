"""Faz birim testleri — hafıza: history-aware rewrite + window + Generator entegrasyonu (stub)."""
import unittest
from dataclasses import dataclass, field

from src.memory import HistoryAwareRewriter, sliding_window, window_context
from src.pricing import Usage


@dataclass
class _Res:
    text: str
    model: str = "deepseek-chat"
    usage: Usage = field(default_factory=lambda: Usage(0, 15, 6, 0))
    latency_s: float = 0.0


class _StubDS:
    def __init__(self, text, raise_exc=False):
        self._text = text
        self.raise_exc = raise_exc
        self.calls = 0

    def chat(self, prompt, system=None, temperature=0.2, max_tokens=None, extra=None):
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("api error")
        return _Res(self._text)


def _noop(**k):
    return None


_HIST = [{"role": "user", "content": "DNA kendini nasıl eşler?"},
         {"role": "assistant", "content": "DNA replikasyonu yarı korunumludur..."}]


class HistoryRewriteTests(unittest.TestCase):
    def test_rewrites_followup_with_history(self):
        ds = _StubDS("DNA replikasyonunu başlatan enzim nedir?")
        rw = HistoryAwareRewriter(ds, cost_recorder=_noop)
        out = rw.rewrite(_HIST, "peki bunu başlatan enzim hangisi?")
        self.assertEqual(out, "DNA replikasyonunu başlatan enzim nedir?")
        self.assertEqual(ds.calls, 1)

    def test_no_history_returns_original_no_llm(self):
        ds = _StubDS("DEĞİŞMEMELİ")
        rw = HistoryAwareRewriter(ds, cost_recorder=_noop)
        out = rw.rewrite([], "DNA nedir?")
        self.assertEqual(out, "DNA nedir?")
        self.assertEqual(ds.calls, 0)              # geçmiş yok → LLM çağrılmaz

    def test_error_fail_safe_returns_original(self):
        ds = _StubDS("x", raise_exc=True)
        rw = HistoryAwareRewriter(ds, cost_recorder=_noop)
        out = rw.rewrite(_HIST, "peki nedeni?")
        self.assertEqual(out, "peki nedeni?")      # FAIL-SAFE: orijinal

    def test_strips_quotes(self):
        ds = _StubDS('"DNA replikasyonu enzimi nedir?"')
        rw = HistoryAwareRewriter(ds, cost_recorder=_noop)
        out = rw.rewrite(_HIST, "o enzim ne?")
        self.assertEqual(out, "DNA replikasyonu enzimi nedir?")

    def test_reasoning_dump_keeps_the_original_query(self):
        dump = ('We need to rewrite the follow-up question "c#" to be '
                'self-contained. So we need to rewrite as a question.')
        rw = HistoryAwareRewriter(_StubDS(dump), cost_recorder=_noop)
        self.assertEqual(rw.rewrite(_HIST, "c#"), "c#")


    def test_cost_recorded(self):
        calls = []
        rw = HistoryAwareRewriter(_StubDS("yeniden yazıldı"),
                                  cost_recorder=lambda **k: calls.append(k))
        rw.rewrite(_HIST, "peki nedeni?")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["module"], "rewrite")


class WindowTests(unittest.TestCase):
    def test_sliding_window_last_n(self):
        h = [{"role": "user", "content": str(i)} for i in range(10)]
        w = sliding_window(h, max_turns=3)
        self.assertEqual([t["content"] for t in w], ["7", "8", "9"])

    def test_empty(self):
        self.assertEqual(sliding_window(None), [])
        self.assertEqual(window_context([]), "")

    def test_window_context_format(self):
        c = window_context(_HIST, max_turns=6)
        self.assertIn("Kullanıcı: DNA kendini nasıl eşler?", c)
        self.assertIn("Asistan:", c)


class _RecordingRetriever:
    """retrieve()'e gelen sorguyu kaydeder (rewrite entegrasyonu testi)."""
    def __init__(self, hits):
        self._hits = hits
        self.last_query = None

    def retrieve(self, query, top_k=20, school=None):
        self.last_query = query
        return self._hits[:top_k]


class GeneratorRewriteIntegrationTests(unittest.TestCase):
    def test_history_rewrite_feeds_retrieval(self):
        # Generator: history + rewriter -> retrieval REWRITTEN sorguyu almalı
        from src.generate import Generator
        # basit stub'lar
        class _Rw:
            def rewrite(self, history, query): return "BAGIMSIZ SORU"
        class _RR:
            def rerank(self, query, items, top_k=None, normalize=True):
                return sorted(((c, 9.0) for c, _ in items), key=lambda x: -x[1])[:top_k]
        class _DS:
            model = "deepseek-chat"
            def __init__(self): self.calls = 0
            def chat(self, prompt, system=None, *, temperature=0.2, max_tokens=None, extra=None):
                self.calls += 1
                from src.providers.llm import ChatResult
                return ChatResult(text="cevap [1].", usage=Usage(0, 10, 5, 0),
                                  model="deepseek-chat", latency_s=0.0)
        from dataclasses import make_dataclass
        Chunk = make_dataclass("Chunk", [("chunk_id", str), ("text", str),
                                         ("parent_id", object), ("span_ids", list)])
        by_id = {"c1": Chunk("c1", "DNA metni", None, ["s1"])}
        span_meta = {"s1": {"page": 10, "bbox": None}}
        retr = _RecordingRetriever([("c1", 1.0)])
        gen = Generator(retr, _RR(), by_id, span_meta, _DS(), cost_recorder=_noop,
                        rewriter=_Rw())
        gen.answer("o ne?", history=_HIST)
        self.assertEqual(retr.last_query, "BAGIMSIZ SORU")   # rewrite retrieval'a gitti

    def test_no_history_uses_original_query(self):
        from src.generate import Generator
        class _Rw:
            def rewrite(self, history, query): return "OLMAMALI"
        class _RR:
            def rerank(self, query, items, top_k=None, normalize=True):
                return sorted(((c, 9.0) for c, _ in items), key=lambda x: -x[1])[:top_k]
        class _DS:
            model = "deepseek-chat"
            def chat(self, prompt, system=None, *, temperature=0.2, max_tokens=None, extra=None):
                from src.providers.llm import ChatResult
                return ChatResult(text="cevap [1].", usage=Usage(0, 10, 5, 0),
                                  model="deepseek-chat", latency_s=0.0)
        from dataclasses import make_dataclass
        Chunk = make_dataclass("Chunk", [("chunk_id", str), ("text", str),
                                         ("parent_id", object), ("span_ids", list)])
        by_id = {"c1": Chunk("c1", "DNA metni", None, ["s1"])}
        retr = _RecordingRetriever([("c1", 1.0)])
        gen = Generator(retr, _RR(), by_id, {"s1": {"page": 10}}, _DS(),
                        cost_recorder=_noop, rewriter=_Rw())
        gen.answer("DNA nedir?")                              # history yok
        self.assertEqual(retr.last_query, "DNA nedir?")      # orijinal sorgu (rewrite atlandı)


if __name__ == "__main__":
    unittest.main()
