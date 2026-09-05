"""Faz 1.7a birim testleri — kaynak-sınırlı üretim + atıf (kaynak yer bulma).

Model/ağ GEREKMEZ: DeepSeek, retriever ve reranker stub'lanır. Odak: (1) prompt
kaynakları doğru numaralıyor + sayfa gösteriyor, (2) [N] atıfları gerçek
chunk_id/sayfaya doğru eşleniyor, (3) FAIL-CLOSED (boş/düşük skor bağlamda LLM
HİÇ çağrılmıyor), (4) hayalet atıf ([N] kaynak sayısını aşarsa) patlamadan
işaretleniyor.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass, field

from src.generate import ABSTAIN_SENTENCE, Generator, GroundedAnswer, build_grounded_prompt
from src.generate.generator import _format_pages
from src.pricing import Usage
from src.providers.deepseek import ChatResult


# --------------------------------------------------------------------------- stub'lar

@dataclass
class _Chunk:
    """rerank_select'in beklediği minimum arayüz (bkz. src/rerank/pipeline.py)."""
    chunk_id: str
    text: str
    parent_id: str | None = None
    span_ids: list = field(default_factory=list)


class _StubRetriever:
    """retrieve(query, top_k) -> [(chunk_id, skor)] (RRF çıktısı taklidi)."""
    def __init__(self, hits):
        self._hits = list(hits)

    def retrieve(self, query, top_k=20):
        return self._hits[:top_k]


class _StubReranker:
    """rerank(query, items) -> [(id, skor)] azalan; skor tam kontrol için sözlükten."""
    def __init__(self, scores: dict):
        self.scores = scores

    def rerank(self, query, items, top_k=None, normalize=True):
        ranked = sorted(((cid, self.scores.get(cid, 0.0)) for cid, _ in items),
                        key=lambda x: -x[1])
        return ranked[:top_k] if top_k else ranked


class _StubDeepSeek:
    """chat() sabit metin + sabit Usage döndürür; çağrı sayacı + son argümanları tutar."""
    def __init__(self, text="X'tir [1]. Y'dir [2].", model="deepseek-chat"):
        self.text = text
        self.model = model
        self.calls = 0
        self.last_prompt = None
        self.last_system = None

    def chat(self, prompt, system=None, *, temperature=0.2, max_tokens=None, extra=None):
        self.calls += 1
        self.last_prompt = prompt
        self.last_system = system
        return ChatResult(text=self.text, usage=Usage(input_cache_hit=0, input_cache_miss=10,
                                                       output=5, reasoning=0),
                          model=self.model, latency_s=0.001)


def _noop_recorder(**kwargs):
    """costlog.record yerine geçer — gerçek Obsidian deftere YAZMAZ (yalnız birim test)."""
    return {"cost_usd": 0.0}


def _corpus():
    """İki bağımsız (parent'sız) chunk + tutarlı span_meta (sayfa 10 ve 25)."""
    chunks_by_id = {
        "c1": _Chunk("c1", "DNA çift sarmal yapıya sahiptir.", None, ["s1"]),
        "c2": _Chunk("c2", "Fotosentez ışığa bağlı bir tepkimedir.", None, ["s2"]),
    }
    span_meta = {
        "s1": {"page": 10, "bbox": (0.0, 0.0, 100.0, 20.0)},
        "s2": {"page": 25, "bbox": (0.0, 0.0, 100.0, 20.0)},
    }
    hits = [("c1", 1.0), ("c2", 0.9)]
    return chunks_by_id, span_meta, hits


def _make_generator(deepseek, scores, ders="biyoloji", abstain_score=0.30, hits=None):
    chunks_by_id, span_meta, default_hits = _corpus()
    retriever = _StubRetriever(hits if hits is not None else default_hits)
    reranker = _StubReranker(scores)
    return Generator(retriever, reranker, chunks_by_id, span_meta, deepseek,
                     ders=ders, abstain_score=abstain_score,
                     cost_recorder=_noop_recorder)


# --------------------------------------------------------------------------- testler

class BuildGroundedPromptTests(unittest.TestCase):
    def test_sources_numbered_with_pages(self):
        sources = [
            {"n": 1, "ders": "biyoloji", "page": "10", "text": "DNA çift sarmaldır."},
            {"n": 2, "ders": "biyoloji", "page": "25", "text": "Fotosentez ışığa bağlıdır."},
        ]
        system, user = build_grounded_prompt("DNA nedir?", sources)
        self.assertIn("[Kaynak 1 | biyoloji s.10]", user)
        self.assertIn("DNA çift sarmaldır.", user)
        self.assertIn("[Kaynak 2 | biyoloji s.25]", user)
        self.assertIn("Fotosentez ışığa bağlıdır.", user)
        self.assertIn("SORU: DNA nedir?", user)
        # sistem promptu: kaynak-dışı bilgi yasak + [N] atıf formatı + çekimser cümle
        self.assertIn("[1]", system)
        self.assertIn("Kaynaklarda bu bilgi bulunamadı.", system)

    def test_missing_page_falls_back_to_placeholder(self):
        sources = [{"n": 1, "ders": "biyoloji", "page": None, "text": "metin"}]
        _, user = build_grounded_prompt("soru", sources)
        self.assertIn("[Kaynak 1 | biyoloji s.?]", user)


class FormatPagesTests(unittest.TestCase):
    """span_meta'dan çıkan sayfa listesinin gösterim biçimi (çoklu/aralıklı sayfa)."""

    def test_empty(self):
        self.assertEqual(_format_pages([]), "?")

    def test_single_page(self):
        self.assertEqual(_format_pages([12]), "12")

    def test_contiguous_range(self):
        self.assertEqual(_format_pages([12, 13, 14]), "12-14")

    def test_disjoint_pages_joined_with_comma(self):
        self.assertEqual(_format_pages([12, 14]), "12,14")

    def test_mixed_ranges_and_singletons(self):
        self.assertEqual(_format_pages([5, 6, 7, 9, 12, 13]), "5-7,9,12-13")

    def test_unsorted_and_duplicate_input_normalized(self):
        # generator.py sorted(set(...)) ile çağırır; fonksiyon zaten sıralı liste bekler
        # ama kaynağı (span_ids -> sayfa) çıkaran kod duplicate/sırasız üretebilir.
        self.assertEqual(_format_pages(sorted(set([14, 12, 12, 13]))), "12-14")


class MultiPageCitationTests(unittest.TestCase):
    """Bir kaynağın span_ids'i birden çok sayfaya yayılınca atıf + prompt doğru gösterir."""

    def test_multi_page_source_shows_range_in_prompt_and_citation(self):
        chunks_by_id = {
            "c1": _Chunk("c1", "Hücre zarı yapısı ve akıcı mozaik model.", None,
                        ["s1", "s2", "s3"]),
        }
        span_meta = {
            "s1": {"page": 40, "bbox": (0, 0, 1, 1)},
            "s2": {"page": 41, "bbox": (0, 0, 1, 1)},
            "s3": {"page": 43, "bbox": (0, 0, 1, 1)},   # süreksiz: 40-41 ve 43
        }
        deepseek = _StubDeepSeek(text="Hücre zarı akıcı mozaik modele göre yapılanır [1].")
        retriever = _StubRetriever([("c1", 1.0)])
        reranker = _StubReranker({"c1": 0.9})
        gen = Generator(retriever, reranker, chunks_by_id, span_meta, deepseek,
                        ders="biyoloji", cost_recorder=_noop_recorder)

        result = gen.answer("hücre zarı yapısı")

        self.assertFalse(result.abstained)
        self.assertIn("[Kaynak 1 | biyoloji s.40-41,43]", deepseek.last_prompt)
        self.assertEqual(result.citations[0]["pages"], [40, 41, 43])


class GeneratorCitationTests(unittest.TestCase):
    def test_prompt_sent_to_llm_has_numbered_sources_and_pages(self):
        deepseek = _StubDeepSeek()
        gen = _make_generator(deepseek, scores={"c1": 0.9, "c2": 0.85})
        result = gen.answer("DNA nedir?")

        self.assertFalse(result.abstained)
        self.assertEqual(deepseek.calls, 1)
        self.assertIn("[Kaynak 1 | biyoloji s.10]", deepseek.last_prompt)
        self.assertIn("[Kaynak 2 | biyoloji s.25]", deepseek.last_prompt)

    def test_citation_parsing_maps_to_correct_chunk_and_page(self):
        deepseek = _StubDeepSeek(text="X'tir [1]. Y'dir [2].")
        gen = _make_generator(deepseek, scores={"c1": 0.9, "c2": 0.85})
        result = gen.answer("DNA nedir?")

        self.assertIsInstance(result, GroundedAnswer)
        self.assertFalse(result.abstained)
        self.assertEqual(result.reason, "")
        self.assertEqual(len(result.citations), 2)

        c_by_n = {c["n"]: c for c in result.citations}
        self.assertEqual(c_by_n[1]["chunk_id"], "c1")
        self.assertEqual(c_by_n[1]["pages"], [10])
        self.assertEqual(c_by_n[1]["span_ids"], ["s1"])
        self.assertEqual(c_by_n[2]["chunk_id"], "c2")
        self.assertEqual(c_by_n[2]["pages"], [25])

        self.assertEqual(result.used_source_ids, ["c1", "c2"])
        self.assertIn("[1]", result.text)
        self.assertIn("[2]", result.text)
        # gerçek (stub) usage'dan hesaplanan maliyet sıfır değil
        self.assertGreater(result.cost_usd, 0.0)
        self.assertEqual(result.usage.output, 5)

    def test_fail_closed_on_empty_context_llm_not_called(self):
        deepseek = _StubDeepSeek()
        gen = _make_generator(deepseek, scores={}, hits=[])   # retriever hiç aday döndürmüyor
        result = gen.answer("alakasız soru")

        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "insufficient_data")
        self.assertEqual(result.text, "Kaynaklarda bu bilgi bulunamadı.")
        self.assertEqual(result.citations, [])
        self.assertEqual(result.cost_usd, 0.0)
        self.assertEqual(deepseek.calls, 0)     # LLM ÇAĞRILMADI

    def test_fail_closed_on_low_rerank_score_llm_not_called(self):
        deepseek = _StubDeepSeek()
        # en iyi skor (0.1) abstain_score (0.30) altında → çekimser dönmeli
        gen = _make_generator(deepseek, scores={"c1": 0.1, "c2": 0.05}, abstain_score=0.30)
        result = gen.answer("belirsiz soru")

        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "insufficient_data")
        self.assertEqual(result.cost_usd, 0.0)
        self.assertEqual(deepseek.calls, 0)     # LLM ÇAĞRILMADI

    def test_phantom_citation_flagged_without_crashing(self):
        # yalnız 2 kaynak var ama LLM [1] ve [5]'e atıf yapıyor (5 hayalet)
        deepseek = _StubDeepSeek(text="X'tir [1]. Ama [5] numaralı kaynağa göre de öyle.")
        gen = _make_generator(deepseek, scores={"c1": 0.9, "c2": 0.85})
        result = gen.answer("DNA nedir?")

        self.assertFalse(result.abstained)          # LLM zaten çağrıldı, bu çağrı-sonrası kontrol
        self.assertEqual(result.reason, "phantom_citation")
        # yalnız geçerli [1] citations'a girer; [5] sessizce elenir (patlama yok)
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0]["n"], 1)
        self.assertEqual(result.citations[0]["chunk_id"], "c1")
        self.assertEqual(result.used_source_ids, ["c1"])


class PostHocAbstainTests(unittest.TestCase):
    """DOĞRULAYICI bulgusu #1: LLM ÇAĞRILDIKTAN SONRA cevap fiilen kaynak-yok
    cümlesine denk düşüyorsa (veya atıfsız + boşsa) abstained=True olmalı;
    LLM gerçekten çağrıldığı için usage/cost_usd GERÇEK kalmalı (sıfırlanmamalı)."""

    def test_exact_abstain_sentence_flags_model_abstained(self):
        deepseek = _StubDeepSeek(text=ABSTAIN_SENTENCE)
        gen = _make_generator(deepseek, scores={"c1": 0.9, "c2": 0.85})
        result = gen.answer("DNA nedir?")

        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "model_abstained")
        self.assertEqual(deepseek.calls, 1)            # LLM GERÇEKTEN çağrıldı
        self.assertIsNotNone(result.usage)
        self.assertGreater(result.cost_usd, 0.0)        # maliyet SIFIRLANMADI

    def test_near_identical_abstain_sentence_flags_model_abstained(self):
        # noktasız + küçük harf + fazladan boşluk — normalize sonrası aynı cümle
        deepseek = _StubDeepSeek(text="kaynaklarda   bu bilgi bulunamadı")
        gen = _make_generator(deepseek, scores={"c1": 0.9, "c2": 0.85})
        result = gen.answer("DNA nedir?")

        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "model_abstained")

    def test_empty_answer_without_valid_citations_flags_model_abstained(self):
        deepseek = _StubDeepSeek(text="   ")
        gen = _make_generator(deepseek, scores={"c1": 0.9, "c2": 0.85})
        result = gen.answer("DNA nedir?")

        self.assertTrue(result.abstained)
        self.assertEqual(result.reason, "model_abstained")
        self.assertGreater(result.cost_usd, 0.0)

    def test_normal_grounded_answer_not_flagged_as_abstain(self):
        deepseek = _StubDeepSeek(text="X'tir [1]. Y'dir [2].")
        gen = _make_generator(deepseek, scores={"c1": 0.9, "c2": 0.85})
        result = gen.answer("DNA nedir?")

        self.assertFalse(result.abstained)
        self.assertEqual(result.reason, "")


class CommaAndAdjacentCitationRegexTests(unittest.TestCase):
    """DOĞRULAYICI bulgusu #2: `[1, 2]`, `[1,2]`, `[1][2]`, `[1] [2]` hepsi
    yakalanmalı; hayalet atıf kuralı hâlâ çalışmalı."""

    def _four_source_generator(self, deepseek):
        chunks_by_id = {
            "c1": _Chunk("c1", "metin1", None, ["s1"]),
            "c2": _Chunk("c2", "metin2", None, ["s2"]),
            "c3": _Chunk("c3", "metin3", None, ["s3"]),
            "c4": _Chunk("c4", "metin4", None, ["s4"]),
        }
        span_meta = {
            "s1": {"page": 1, "bbox": (0, 0, 1, 1)}, "s2": {"page": 2, "bbox": (0, 0, 1, 1)},
            "s3": {"page": 3, "bbox": (0, 0, 1, 1)}, "s4": {"page": 4, "bbox": (0, 0, 1, 1)},
        }
        hits = [("c1", 1.0), ("c2", 0.9), ("c3", 0.8), ("c4", 0.7)]
        retriever = _StubRetriever(hits)
        reranker = _StubReranker({"c1": 0.9, "c2": 0.85, "c3": 0.8, "c4": 0.75})
        return Generator(retriever, reranker, chunks_by_id, span_meta, deepseek,
                         ders="biyoloji", cost_recorder=_noop_recorder)

    def test_comma_and_adjacent_bracket_forms_all_parsed(self):
        # "[1, 2]" (virgüllü tek parantez) + "[3][4]" (bitişik iki parantez)
        deepseek = _StubDeepSeek(text="X [1, 2]. Y [3][4].")
        gen = self._four_source_generator(deepseek)
        result = gen.answer("soru", top_n=4)

        self.assertFalse(result.abstained)
        self.assertEqual({c["n"] for c in result.citations}, {1, 2, 3, 4})
        self.assertEqual(result.invalid_citations, [])

    def test_no_space_comma_and_spaced_adjacent_forms_all_parsed(self):
        # "[1,2]" (boşluksuz virgül) + "[3] [4]" (aralarında boşluklu iki parantez)
        deepseek = _StubDeepSeek(text="X [1,2]. Y [3] [4].")
        gen = self._four_source_generator(deepseek)
        result = gen.answer("soru", top_n=4)

        self.assertFalse(result.abstained)
        self.assertEqual({c["n"] for c in result.citations}, {1, 2, 3, 4})

    def test_phantom_still_flagged_with_comma_citation(self):
        # [1, 9]: 1 geçerli, 9 hayalet (yalnız 2 kaynak var) — patlamadan işaretlenmeli
        deepseek = _StubDeepSeek(text="X [1, 9].")
        gen = _make_generator(deepseek, scores={"c1": 0.9, "c2": 0.85})
        result = gen.answer("DNA nedir?")

        self.assertFalse(result.abstained)
        self.assertEqual(result.reason, "phantom_citation")
        self.assertEqual(result.invalid_citations, [9])
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0]["n"], 1)


class AllCitationsPhantomTests(unittest.TestCase):
    """DOĞRULAYICI bulgusu #6: cevap [N] içeriyor ama HİÇBİRİ geçerli değilse
    reason="all_citations_phantom" olmalı + hangi N'lerin hayalet olduğu
    invalid_citations'da saklanmalı."""

    def test_all_citations_phantom_reason_and_invalid_list(self):
        # yalnız 2 kaynak var; LLM sadece geçersiz [5] ve [7]'ye atıf yapıyor
        deepseek = _StubDeepSeek(text="Bir cevap ama [5] ve [7] numaralı kaynaklara göre.")
        gen = _make_generator(deepseek, scores={"c1": 0.9, "c2": 0.85})
        result = gen.answer("DNA nedir?")

        self.assertFalse(result.abstained)   # boş değil, LLM gerçek metin üretti
        self.assertEqual(result.reason, "all_citations_phantom")
        self.assertEqual(result.citations, [])
        self.assertEqual(sorted(result.invalid_citations), [5, 7])


class ParentTextContextTests(unittest.TestCase):
    """DOĞRULAYICI bulgusu #4: RerankedContext.parent_text varsa LLM bağlamına
    ayrı, net biçimde ("Genişletilmiş bağlam: ...") eklenmeli; atıf/sayfa YİNE
    child span'dan hesaplanmalı (mimari §0.1 — atıf leaf'te kalır)."""

    def test_parent_text_in_prompt_but_citation_uses_child_span(self):
        chunks_by_id = {
            "child1": _Chunk("child1", "Mitokondri enerji üretir.", "parent1", ["s1"]),
            "parent1": _Chunk("parent1", "GENISLETILMIS_PARENT_METNI hücre organelleri...",
                              None, []),
        }
        span_meta = {"s1": {"page": 55, "bbox": (0, 0, 1, 1)}}
        deepseek = _StubDeepSeek(text="Mitokondri enerji üretir [1].")
        retriever = _StubRetriever([("child1", 1.0)])
        reranker = _StubReranker({"child1": 0.9})
        gen = Generator(retriever, reranker, chunks_by_id, span_meta, deepseek,
                        ders="biyoloji", cost_recorder=_noop_recorder)

        result = gen.answer("mitokondri nedir?")

        self.assertFalse(result.abstained)
        # parent bağlamı prompt'ta AYRI, NET işaretle görünür
        self.assertIn("Genişletilmiş bağlam:", deepseek.last_prompt)
        self.assertIn("GENISLETILMIS_PARENT_METNI", deepseek.last_prompt)
        self.assertIn("Mitokondri enerji üretir.", deepseek.last_prompt)
        # atıf/sayfa YİNE child'dan (parent'ın kendi span'ı/sayfası yok)
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0]["chunk_id"], "child1")
        self.assertEqual(result.citations[0]["span_ids"], ["s1"])
        self.assertEqual(result.citations[0]["pages"], [55])

    def test_no_parent_text_omits_expanded_context_label(self):
        # parent_id yok → parent_text yok → "Genişletilmiş bağlam:" ASLA görünmemeli
        deepseek = _StubDeepSeek()
        gen = _make_generator(deepseek, scores={"c1": 0.9, "c2": 0.85})
        gen.answer("DNA nedir?")

        self.assertNotIn("Genişletilmiş bağlam:", deepseek.last_prompt)


class CostRecorderSpyTests(unittest.TestCase):
    """DOĞRULAYICI bulgusu #7: costlog.record'a (ya da enjekte edilen
    cost_recorder'a) doğru module/model/usage argümanlarıyla çağrı yapıldığını
    doğrula — record çağrısı silinirse bu test KIRILMALI."""

    def test_cost_recorder_called_with_expected_module_model_usage(self):
        calls = []

        def spy(**kwargs):
            calls.append(kwargs)
            return {"cost_usd": 0.0}

        deepseek = _StubDeepSeek(text="X'tir [1]. Y'dir [2].", model="deepseek-chat")
        chunks_by_id, span_meta, hits = _corpus()
        retriever = _StubRetriever(hits)
        reranker = _StubReranker({"c1": 0.9, "c2": 0.85})
        gen = Generator(retriever, reranker, chunks_by_id, span_meta, deepseek,
                        ders="biyoloji", module="chat", cost_recorder=spy)

        result = gen.answer("DNA nedir?")

        self.assertFalse(result.abstained)
        self.assertEqual(len(calls), 1, "cost_recorder tam olarak bir kez çağrılmalı")
        call = calls[0]
        self.assertEqual(call["module"], "chat")
        self.assertEqual(call["model"], "deepseek-chat")
        self.assertIs(call["usage"], result.usage)
        self.assertEqual(call["items"], 1)
        self.assertIn("top_n", call.get("config", {}))

    def test_cost_recorder_not_called_on_fail_closed_abstain(self):
        # LLM hiç çağrılmadığı için cost_recorder da çağrılmamalı
        calls = []

        def spy(**kwargs):
            calls.append(kwargs)
            return {"cost_usd": 0.0}

        deepseek = _StubDeepSeek()
        gen = _make_generator(deepseek, scores={}, hits=[])
        gen._record = spy
        result = gen.answer("alakasız soru")

        self.assertTrue(result.abstained)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
