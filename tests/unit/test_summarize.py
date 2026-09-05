"""Özet ÇIKARMA mimarisi birim testleri (src/summarize/) — soru-cevaptan AYRI.

Model/ağ GEREKMEZ: DeepSeek STUB'lanır (gerçek DeepSeek/costlog dosyasına ASLA
yazılmaz). Odak: (1) `resolve_scope` sayfa/span_id kapsamını DETERMİNİSTİK
çözüyor + retrieval_disi hariç tutuyor, (2) prompt numaralı kaynak blokları +
detay/atıf talimatı içeriyor, (3) FAIL-CLOSED (boş kapsamda LLM HİÇ çağrılmıyor),
(4) tek-geçiş atıf eşleme, (5) hiyerarşik (RAPTOR-benzeri) akış + atıf taşıma,
(6) cost_recorder'a doğru module ile çağrı yapıldığı.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass, field

from src.providers.deepseek import ChatResult
from src.pricing import Usage
from src.summarize import GroundedSummary, Summarizer, build_summary_prompt, resolve_scope
from src.summarize.prompt import NO_CONTENT_SENTENCE


# --------------------------------------------------------------------------- stub'lar

@dataclass
class _Unit:
    """CanonicalUnit'in resolve_scope/summarizer için gereken minimum arayüzü.
    Gerçek `build_canonical` ÇALIŞTIRILMAZ — saf, elle kurulan stub."""
    span_id: str
    page: int
    text: str
    retrieval_disi: bool = False

    @property
    def retrievable(self) -> bool:
        return not self.retrieval_disi


@dataclass
class _Doc:
    """CanonicalDoc'un resolve_scope için gereken minimum arayüzü (yalnız `.units`)."""
    units: list = field(default_factory=list)


class _StubDeepSeek:
    """chat() sabit metin (veya çağrı-sırasına göre metin listesi) + sabit Usage
    döndürür; çağrı sayacı + gönderilen promptları tutar."""

    def __init__(self, text="Özet [1].", texts=None, model="deepseek-chat"):
        self.text = text
        self._texts = list(texts) if texts is not None else None
        self.model = model
        self.calls = 0
        self.last_prompt = None
        self.last_system = None
        self.prompts: list[str] = []

    def chat(self, prompt, system=None, *, temperature=0.3, max_tokens=None, extra=None):
        self.calls += 1
        self.last_prompt = prompt
        self.last_system = system
        self.prompts.append(prompt)
        if self._texts is not None:
            text = self._texts[min(self.calls - 1, len(self._texts) - 1)]
        else:
            text = self.text
        return ChatResult(text=text, usage=Usage(input_cache_hit=0, input_cache_miss=10,
                                                  output=5, reasoning=0),
                          model=self.model, latency_s=0.001)


def _noop_recorder(**kwargs):
    """costlog.record yerine geçer — gerçek Obsidian deftere YAZMAZ (yalnız birim test)."""
    return {"cost_usd": 0.0}


def _five_units():
    return [
        _Unit("s1", 1, "metin1"),
        _Unit("s2", 2, "metin2"),
        _Unit("s3", 3, "metin3"),
        _Unit("s4", 4, "metin4"),
        _Unit("s5", 5, "metin5"),
    ]


# --------------------------------------------------------------------------- resolve_scope

class ResolveScopeTests(unittest.TestCase):
    def _doc(self):
        units = [
            _Unit("s1", 1, "metin1"),
            _Unit("s2", 2, "metin2"),
            _Unit("s3", 3, "metin3"),
            _Unit("s3b", 3, "gizli-metin", retrieval_disi=True),   # indekse/özete girmez
            _Unit("s4", 4, "metin4"),
            _Unit("s5", 5, "metin5"),
        ]
        return _Doc(units=units)

    def test_page_range_returns_matching_units_in_read_order(self):
        doc = self._doc()
        out = resolve_scope(doc, pages=[2, 3])
        self.assertEqual([u.span_id for u in out], ["s2", "s3"])   # s3b (retrieval_disi) HARİÇ

    def test_span_ids_returns_matching_units_in_read_order(self):
        doc = self._doc()
        out = resolve_scope(doc, span_ids=["s5", "s1"])   # sırasız verilse de okuma sırası korunur
        self.assertEqual([u.span_id for u in out], ["s1", "s5"])

    def test_pages_and_span_ids_combined_are_union(self):
        doc = self._doc()
        out = resolve_scope(doc, pages=[1], span_ids=["s4"])
        self.assertEqual([u.span_id for u in out], ["s1", "s4"])

    def test_retrieval_disi_unit_excluded_even_if_page_matches(self):
        doc = self._doc()
        out = resolve_scope(doc, pages=[3])
        self.assertEqual([u.span_id for u in out], ["s3"])
        self.assertNotIn("s3b", [u.span_id for u in out])

    def test_no_scope_given_returns_empty_list(self):
        doc = self._doc()
        self.assertEqual(resolve_scope(doc), [])
        self.assertEqual(resolve_scope(doc, pages=None, span_ids=None), [])

    def test_empty_scope_args_return_empty_list(self):
        doc = self._doc()
        self.assertEqual(resolve_scope(doc, pages=[], span_ids=[]), [])

    def test_scope_matching_nothing_returns_empty_list(self):
        doc = self._doc()
        self.assertEqual(resolve_scope(doc, pages=[999]), [])


# --------------------------------------------------------------------------- prompt

class BuildSummaryPromptTests(unittest.TestCase):
    def test_sources_numbered_with_pages_and_detail_citation_instructions(self):
        blocks = [
            {"n": 1, "page": 10, "text": "DNA çift sarmaldır."},
            {"n": 2, "page": 25, "text": "Fotosentez ışığa bağlıdır."},
        ]
        system, user = build_summary_prompt(blocks, scope_label="s.10-25")

        self.assertIn("[Kaynak 1 | s.10]", user)
        self.assertIn("DNA çift sarmaldır.", user)
        self.assertIn("[Kaynak 2 | s.25]", user)
        self.assertIn("Fotosentez ışığa bağlıdır.", user)
        self.assertIn("KAPSAM: s.10-25", user)

        # sistem promptu: detay talimatı + [N] atıf formatı + içerik-yok cümlesi
        self.assertIn("DETAYLI", system)
        self.assertIn("[N]", system)
        self.assertIn(NO_CONTENT_SENTENCE, system)

    def test_missing_page_falls_back_to_placeholder(self):
        blocks = [{"n": 1, "page": None, "text": "metin"}]
        _, user = build_summary_prompt(blocks)
        self.assertIn("[Kaynak 1 | s.?]", user)

    def test_no_scope_label_omits_kapsam_line(self):
        blocks = [{"n": 1, "page": 1, "text": "metin"}]
        _, user = build_summary_prompt(blocks)
        self.assertNotIn("KAPSAM:", user)


# --------------------------------------------------------------------------- summarize: FAIL-CLOSED

class FailClosedTests(unittest.TestCase):
    def test_empty_units_abstains_without_calling_llm(self):
        ds = _StubDeepSeek()
        summarizer = Summarizer(ds, cost_recorder=_noop_recorder)

        result = summarizer.summarize([])

        self.assertIsInstance(result, GroundedSummary)
        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "empty_scope")
        self.assertEqual(result.text, NO_CONTENT_SENTENCE)
        self.assertEqual(result.cost_usd, 0.0)
        self.assertEqual(result.citations, [])
        self.assertEqual(result.n_source_units, 0)
        self.assertFalse(result.hierarchical)
        self.assertEqual(ds.calls, 0, "LLM ÇAĞRILMAMALI (boş kapsam)")

    def test_cost_recorder_not_called_on_empty_scope(self):
        calls = []

        def spy(**kwargs):
            calls.append(kwargs)
            return {"cost_usd": 0.0}

        ds = _StubDeepSeek()
        summarizer = Summarizer(ds, cost_recorder=spy)
        summarizer.summarize([])

        self.assertEqual(calls, [])


# --------------------------------------------------------------------------- summarize: tek geçiş

class SinglePassTests(unittest.TestCase):
    def test_single_pass_citations_map_to_correct_span_and_page(self):
        units = [
            _Unit("s1", 10, "DNA çift sarmal yapıya sahiptir."),
            _Unit("s2", 25, "Fotosentez ışığa bağlı bir tepkimedir."),
        ]
        ds = _StubDeepSeek(text="DNA hakkında özet [1]. Fotosentez hakkında özet [2].")
        summarizer = Summarizer(ds, cost_recorder=_noop_recorder, max_units_per_group=12)

        result = summarizer.summarize(units, scope_label="s.10-25")

        self.assertFalse(result.abstained)
        self.assertFalse(result.hierarchical)
        self.assertEqual(ds.calls, 1)
        self.assertEqual(result.n_source_units, 2)
        self.assertEqual(result.scope_pages, [10, 25])

        c_by_n = {c["n"]: c for c in result.citations}
        self.assertEqual(len(c_by_n), 2)
        self.assertEqual(c_by_n[1]["span_ids"], ["s1"])
        self.assertEqual(c_by_n[1]["pages"], [10])
        self.assertEqual(c_by_n[2]["span_ids"], ["s2"])
        self.assertEqual(c_by_n[2]["pages"], [25])

        self.assertGreater(result.cost_usd, 0.0)
        self.assertIsNotNone(result.usage)
        self.assertIn("[Kaynak 1 | s.10]", ds.last_prompt)
        self.assertIn("[Kaynak 2 | s.25]", ds.last_prompt)

    def test_phantom_citation_silently_dropped_without_crashing(self):
        units = [_Unit("s1", 1, "metin1")]
        ds = _StubDeepSeek(text="Bir özet [1] ve hayali [9].")
        summarizer = Summarizer(ds, cost_recorder=_noop_recorder)

        result = summarizer.summarize(units)

        self.assertFalse(result.abstained)
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0]["n"], 1)

    def test_comma_and_adjacent_bracket_citation_forms_parsed(self):
        units = [_Unit("s1", 1, "m1"), _Unit("s2", 2, "m2"),
                 _Unit("s3", 3, "m3"), _Unit("s4", 4, "m4")]
        ds = _StubDeepSeek(text="X [1, 2]. Y [3][4].")
        summarizer = Summarizer(ds, cost_recorder=_noop_recorder)

        result = summarizer.summarize(units)

        self.assertEqual({c["n"] for c in result.citations}, {1, 2, 3, 4})


# --------------------------------------------------------------------------- summarize: hiyerarşik

class HierarchicalTests(unittest.TestCase):
    def test_hierarchical_triggered_above_max_units_per_group(self):
        units = _five_units()
        texts = [
            "Grup1 özeti [1][2].",     # group 1: units s1,s2
            "Grup2 özeti [1].",        # group 2: units s3,s4 -> yalnız ilkine (s3) atıf
            "Grup3 özeti [1].",        # group 3: unit s5
            "Nihai özet [1][2][3].",   # birleştirme: 3 ara-özete atıf
        ]
        ds = _StubDeepSeek(texts=texts)
        summarizer = Summarizer(ds, cost_recorder=_noop_recorder, max_units_per_group=2)

        result = summarizer.summarize(units)

        self.assertTrue(result.hierarchical)
        self.assertFalse(result.abstained)
        self.assertEqual(result.n_source_units, 5)
        self.assertEqual(result.scope_pages, [1, 2, 3, 4, 5])
        self.assertEqual(ds.calls, 4, "3 grup + 1 birleştirme çağrısı")
        self.assertEqual(result.text, "Nihai özet [1][2][3].")

        c_by_n = {c["n"]: c for c in result.citations}
        self.assertEqual(set(c_by_n), {1, 2, 3})
        # n=1 -> grup1'in atıflarındaki ham leaf span'lar (s1, s2) taşınmış olmalı
        self.assertEqual(sorted(c_by_n[1]["span_ids"]), ["s1", "s2"])
        self.assertEqual(sorted(c_by_n[1]["pages"]), [1, 2])
        # n=2 -> grup2'nin GERÇEKTEN atıfladığı tek span (s3) — s4 atıflanmadığı
        # için TAŞINMAZ (sahte doldurma yapılmaz, pass-bias YASAK)
        self.assertEqual(c_by_n[2]["span_ids"], ["s3"])
        self.assertNotIn("s4", c_by_n[2]["span_ids"])
        # n=3 -> grup3'ün tek span'ı (s5)
        self.assertEqual(c_by_n[3]["span_ids"], ["s5"])

        self.assertGreater(result.cost_usd, 0.0)
        self.assertIsNotNone(result.usage)
        # birleşik usage: 4 gerçek çağrının toplamı (her biri output=5)
        self.assertEqual(result.usage.output, 20)

    def test_hierarchical_group_with_no_valid_citation_carries_empty_span_ids(self):
        # grup, kendi biriminde HİÇ atıf yapmazsa nihai atıf da BOŞ span/sayfa
        # taşımalı (sahte doldurma YOK) — pass-bias YASAK ilkesinin doğrudan testi.
        units = [_Unit("s1", 1, "m1"), _Unit("s2", 2, "m2"), _Unit("s3", 3, "m3")]
        texts = [
            NO_CONTENT_SENTENCE,     # grup1 (s1,s2): atıf yok
            "Grup2 özeti [1].",      # grup2 (s3): atıflı
            "Nihai özet [1][2].",    # birleştirme
        ]
        ds = _StubDeepSeek(texts=texts)
        summarizer = Summarizer(ds, cost_recorder=_noop_recorder, max_units_per_group=2)

        result = summarizer.summarize(units)

        self.assertTrue(result.hierarchical)
        c_by_n = {c["n"]: c for c in result.citations}
        self.assertEqual(c_by_n[1]["span_ids"], [])
        self.assertEqual(c_by_n[1]["pages"], [])
        self.assertEqual(c_by_n[2]["span_ids"], ["s3"])


# --------------------------------------------------------------------------- cost_recorder spy

class CostRecorderSpyTests(unittest.TestCase):
    def test_cost_recorder_called_with_ozet_module_single_pass(self):
        calls = []

        def spy(**kwargs):
            calls.append(kwargs)
            return {"cost_usd": 0.0}

        units = [_Unit("s1", 1, "m1")]
        ds = _StubDeepSeek(text="Özet [1].")
        summarizer = Summarizer(ds, module="ozet", cost_recorder=spy)

        result = summarizer.summarize(units)

        self.assertFalse(result.abstained)
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call["module"], "ozet")
        self.assertEqual(call["model"], "deepseek-chat")
        self.assertIs(call["usage"], result.usage)
        self.assertEqual(call["items"], 1)

    def test_cost_recorder_called_once_per_real_llm_call_hierarchical(self):
        calls = []

        def spy(**kwargs):
            calls.append(kwargs)
            return {"cost_usd": 0.0}

        units = _five_units()
        texts = ["Grup1 [1][2].", "Grup2 [1].", "Grup3 [1].", "Nihai [1][2][3]."]
        ds = _StubDeepSeek(texts=texts)
        summarizer = Summarizer(ds, module="ozet", cost_recorder=spy, max_units_per_group=2)

        summarizer.summarize(units)

        self.assertEqual(len(calls), 4, "3 grup + 1 birleştirme -> 4 ayrı costlog kaydı")
        self.assertTrue(all(c["module"] == "ozet" for c in calls))


if __name__ == "__main__":
    unittest.main()
