"""M0-4 (#36) — üç ölçüm modu testleri (retrieval_only / oracle_context / end_to_end).

NEDEN bu dosya var (EXP-010/EVAL-09): `RES-003 §8` "3 testi ayır" diyor ama runner
tek mod koşuyordu (`grep oracle` → 0 sonuç). Sonuç: ölçülen citation precision
0.645 ve correctness 0.838 sayılarında **retrieval mi generator mı** payı olduğu
ayrılamıyordu; EXP-008'in "küçük kayma → regresyon değil" yorumu doğrulanamıyordu.

Testler hermetiktir: gerçek PDF/model/LLM YOK — stub retriever/reranker/LLM ile
`_eval_item`'in üç moddaki davranışı sınanır.
"""
import unittest
from dataclasses import dataclass, field

from src.eval import runner as R


# ── sahte boru hattı parçaları ──────────────────────────────────────────────
@dataclass
class _Chunk:
    chunk_id: str
    level: str
    text: str
    span_ids: list
    page_start: int
    page_end: int
    parent_id: str | None = None
    doc_id: str = "doc"
    sinif: str = "12"
    ders: str = "biyoloji"
    kaynak_turu: str = "ders_kitabi"
    kinds: list = field(default_factory=list)
    page_visual: str = "low_visual"
    approx_tokens: int = 100


class _StubRetriever:
    """Gold'u 3. sırada döndürür → retrieval_only'de sıralama ölçülebilir."""

    def __init__(self, order):
        self.order = order

    def retrieve(self, query, top_k=20, **kw):
        return [(cid, 0.5) for cid in self.order[:top_k]]


class _StubReranker:
    def rerank(self, query, pairs):
        return [(cid, 0.9) for cid, _t in pairs]


class _StubDeepSeek:
    """Kaynak 1'i atıflayan sabit cevap; kaç kez çağrıldığını sayar."""

    def __init__(self, text="Hucre zari secici gecirgendir [1]."):
        self.text = text
        self.calls = 0
        self._api_key = "test"

    def chat(self, prompt, system=None, **kw):
        from src.pricing import Usage
        from src.providers.deepseek import ChatResult
        self.calls += 1
        return ChatResult(text=self.text, usage=Usage(input_cache_miss=10, output=5),
                          model="stub", latency_s=0.0, raw={})


def _pipeline(deepseek=None):
    """c1 gold, c2/c3 çeldirici; c1 ve c2 AYNI parent'ta (oracle'da ikisi de gerekir)."""
    chunks = {
        "c1": _Chunk("c1", "child", "gold metin bir", ["d#10.0"], 10, 10, parent_id="p1"),
        "c2": _Chunk("c2", "child", "gold metin iki", ["d#11.0"], 11, 11, parent_id="p1"),
        "c3": _Chunk("c3", "child", "alakasiz metin", ["d#90.0"], 90, 90, parent_id="p9"),
        "p1": _Chunk("p1", "parent", "parent metni", ["d#10.0", "d#11.0"], 10, 11),
    }
    span_meta = {"d#10.0": {"page": 10, "bbox": (0, 0, 1, 1)},
                 "d#11.0": {"page": 11, "bbox": (0, 0, 1, 1)},
                 "d#90.0": {"page": 90, "bbox": (0, 0, 1, 1)}}
    ds = deepseek or _StubDeepSeek()
    from src.generate import Generator
    gen = Generator(_StubRetriever(["c3", "c3", "c1", "c2"]), _StubReranker(),
                    chunks, span_meta, ds, ders="biyoloji", abstain_score=0.30,
                    module="test", cost_recorder=lambda **kw: None)
    return {"chunks_by_id": chunks, "span_meta": span_meta,
            "retriever": _StubRetriever(["c3", "c3", "c1", "c2"]),
            "reranker": _StubReranker(), "generator": gen, "doc": None}, ds


_ITEM = {"id": "t1", "soru": "Hucre zari nedir?", "kategori": "orta",
         "unite": "U1", "kazanim_kod": "1.1", "critical": False,
         "beklenen_davranis": "cevapla",
         "gold_kaynak_spanlar": ["d#10.0", "d#11.0"], "gold_sayfalar": [10, 11],
         "gold_cevap": "gold cevap", "zararli_kategori": None}


class ModeValidationTests(unittest.TestCase):
    def test_modes_exported(self):
        self.assertEqual(R.EVAL_MODES,
                         ("retrieval_only", "oracle_context", "end_to_end"))

    def test_unknown_mode_rejected(self):
        pl, _ = _pipeline()
        with self.assertRaises(ValueError):
            R._eval_item(_ITEM, pl, None, set(), mode="uydurma")


class RetrievalOnlyTests(unittest.TestCase):
    def test_no_llm_call_at_all(self):
        """Bu modun tek gerekçesi: LLM'siz, ucuz, CI'da koşabilir."""
        pl, ds = _pipeline()
        out = R._eval_item(_ITEM, pl, None, set(), mode="retrieval_only")
        self.assertEqual(ds.calls, 0)
        self.assertEqual(out["mode"], "retrieval_only")
        self.assertEqual(out["generation"]["cost_usd"], 0.0)
        self.assertEqual(out["generation"]["reason"], "retrieval_only")

    def test_retrieval_metrics_still_computed(self):
        pl, _ = _pipeline()
        out = R._eval_item(_ITEM, pl, None, set(), mode="retrieval_only")
        r = out["retrieval"]
        self.assertAlmostEqual(r["recall_at_10"], 1.0)      # c1+c2 ilk 10'da
        self.assertEqual(r["n_gold_spans"], 2)
        self.assertIsNotNone(r["ndcg_at_10"])

    def test_citation_and_judge_are_empty_not_zero(self):
        """Ölçülmeyen şey 0.0 değil None olmalı ('ölçülmedi' != 'başarısız')."""
        pl, _ = _pipeline()
        out = R._eval_item(_ITEM, pl, None, set(), mode="retrieval_only")
        self.assertIsNone(out["citation"]["precision_page"])
        self.assertIsNone(out["judge"])
        self.assertIsNone(out["guardrail"]["abstained"])


class RerankMeasuredAlwaysTests(unittest.TestCase):
    def test_post_rerank_block_present_without_judge_ids(self):
        """M0-3 (#35): rerank ARTIK judge_ids'e bağlı değil — her item'da ölçülür.
        Eskiden 200 item'ın 178'inde reranker etkisi hiç ölçülmüyordu."""
        pl, _ = _pipeline()
        out = R._eval_item(_ITEM, pl, None, set(), mode="retrieval_only")
        self.assertIn("retrieval_post_rerank", out)
        self.assertIsNotNone(out["retrieval_post_rerank"]["recall_at_10"])

    def test_fallback_rescues_second_gold_when_candidates_are_few(self):
        """DÜRÜST DAVRANIŞ: aday az olduğunda `rerank_select`'in fallback döngüsü
        çeşitlilik kısıtının düşürdüğü ikinci gold'u geri getiriyor (ACC-06 bunu
        "fallback kurtardı, ama 4. sırada" diye not etmişti)."""
        pl, _ = _pipeline()
        out = R._eval_item(_ITEM, pl, None, set(), mode="retrieval_only")
        self.assertEqual(out["retrieval"]["all_evidence_recall_at_10"], 1.0)
        self.assertEqual(out["retrieval_post_rerank"]["all_evidence_recall_at_10"], 1.0)

    def test_diversity_constraint_no_longer_drops_second_gold(self):
        """ACC-06 DÜZELDİ (#59, 2026-09-12) — bu test sözleşmeyi çevirdi.

        Eskiden: top_n'i dolduracak kadar FARKLI parent varsa aynı parent'taki
        ikinci gold kanıt eleniyor, fallback de devreye girmiyordu; rerank
        sonrası `all_evidence_recall` **0,0**'a düşüyordu (kısmi kredi veren
        `recall` 0,5 diyerek kaybı gizliyordu).

        Artık çeşitlilik kısıtı tavan değil TABAN: yuvaların bir kısmı saf skor
        sırasına, kalanı yeni parent'lara ayrılıyor. İkinci gold kanıt hayatta
        kalmalı. Kaybın gerçekten olduğu `diversity_share=1.0` ile ayrıca
        `tests/unit/test_rerank.py`'de kayıtlı."""
        chunks = {
            "c1": _Chunk("c1", "child", "gold bir", ["d#10.0"], 10, 10, parent_id="p1"),
            "c2": _Chunk("c2", "child", "gold iki", ["d#11.0"], 11, 11, parent_id="p1"),
        }
        order = ["c1", "c2"]
        for k in range(2, 9):                      # 7 farklı parent'lı çeldirici
            cid = f"d{k}"
            chunks[cid] = _Chunk(cid, "child", f"alakasiz {k}", [f"d#{90 + k}.0"],
                                 90 + k, 90 + k, parent_id=f"p{k}")
            order.append(cid)
        span_meta = {u: {"page": 1, "bbox": (0, 0, 1, 1)}
                     for ch in chunks.values() for u in ch.span_ids}
        ds = _StubDeepSeek()
        from src.generate import Generator
        gen = Generator(_StubRetriever(order), _StubReranker(), chunks, span_meta, ds,
                        ders="biyoloji", abstain_score=0.30, module="test",
                        cost_recorder=lambda **kw: None)
        pl = {"chunks_by_id": chunks, "span_meta": span_meta,
              "retriever": _StubRetriever(order), "reranker": _StubReranker(),
              "generator": gen, "doc": None}
        out = R._eval_item(_ITEM, pl, None, set(), mode="retrieval_only")
        self.assertEqual(out["retrieval"]["all_evidence_recall_at_10"], 1.0)
        self.assertEqual(out["retrieval_post_rerank"]["all_evidence_recall_at_10"], 1.0,
                         "ikinci gold kanıt rerank sonrası yine kayboldu")
        self.assertAlmostEqual(out["retrieval_post_rerank"]["recall_at_10"], 1.0)


class OracleContextTests(unittest.TestCase):
    def test_oracle_uses_gold_chunks_only(self):
        pl, ds = _pipeline()
        out = R._eval_item(_ITEM, pl, None, set(), mode="oracle_context")
        self.assertEqual(out["mode"], "oracle_context")
        self.assertEqual(out["n_oracle_chunks"], 2)        # c1 + c2
        self.assertEqual(ds.calls, 1)                      # üretim yolu koştu

    def test_oracle_chunk_ids_are_page_ordered(self):
        pl, _ = _pipeline()
        ids = R._oracle_chunk_ids({"d#10.0", "d#11.0"}, pl["chunks_by_id"])
        self.assertEqual(ids, ["c1", "c2"])                # sayfa sırası, deterministik

    def test_oracle_excludes_parent_chunks(self):
        """Parent chunk gold span taşısa bile oracle'a GİRMEZ (yalnız child)."""
        pl, _ = _pipeline()
        ids = R._oracle_chunk_ids({"d#10.0"}, pl["chunks_by_id"])
        self.assertEqual(ids, ["c1"])
        self.assertNotIn("p1", ids)

    def test_oracle_disables_parent_expansion(self):
        """DÜRÜST SINIR: parent genişletme bir retrieval kararı; oracle'da kapalı
        (ACC-03'ün yanlış-sayfa gürültüsünü taşımamak için)."""
        pl, _ = _pipeline()
        gen, ids = R._oracle_generator(pl, {"d#10.0", "d#11.0"})
        for cid in ids:
            self.assertIsNone(gen.chunks_by_id[cid].parent_id)

    def test_oracle_inherits_production_settings(self):
        """Oracle, üretim Generator'ının AYNI ayarlarıyla kurulmalı — aksi hâlde
        ölçülen şey üretimi temsil etmez."""
        pl, _ = _pipeline()
        gen, _ = R._oracle_generator(pl, {"d#10.0"})
        base = pl["generator"]
        self.assertEqual(gen.abstain_score, base.abstain_score)
        self.assertEqual(gen.ders, base.ders)
        self.assertEqual(gen.context_packing, base.context_packing)
        self.assertIs(gen.deepseek, base.deepseek)

    def test_item_without_gold_is_skipped_not_scored(self):
        """Kapsam-dışı/zararlı item oracle'da ANLAMSIZ → atlanır, 0.0 sayılmaz."""
        edge = dict(_ITEM, id="e1", beklenen_davranis="cekimser",
                    gold_kaynak_spanlar=[], gold_sayfalar=[], gold_cevap=None)
        pl, ds = _pipeline()
        out = R._eval_item(edge, pl, None, set(), mode="oracle_context")
        self.assertIn("skipped", out)
        self.assertEqual(ds.calls, 0)
        self.assertIsNone(out["citation"]["precision_page"])


class EndToEndTests(unittest.TestCase):
    def test_default_mode_is_end_to_end(self):
        pl, ds = _pipeline()
        out = R._eval_item(_ITEM, pl, None, set())
        self.assertEqual(out["mode"], "end_to_end")
        self.assertEqual(ds.calls, 1)
        self.assertIsNone(out["n_oracle_chunks"])

    def test_uses_real_retriever_not_oracle(self):
        pl, _ = _pipeline()
        e2e = R._eval_item(_ITEM, pl, None, set())
        oracle = R._eval_item(_ITEM, pl, None, set(), mode="oracle_context")
        # e2e retriever alakasız c3'ü de getiriyor, oracle getirmiyor
        self.assertIsNone(e2e["n_oracle_chunks"])
        self.assertEqual(oracle["n_oracle_chunks"], 2)

    def test_error_attribution_is_computable(self):
        """#36'nın amacı: e2e ile oracle arasındaki fark retrieval'ın payı."""
        pl, _ = _pipeline()
        e2e = R._eval_item(_ITEM, pl, None, set())
        oracle = R._eval_item(_ITEM, pl, None, set(), mode="oracle_context")
        for out in (e2e, oracle):
            self.assertIsNotNone(out["citation"]["recall_page"])
        # ikisi de sayı döndürüyorsa fark hesaplanabilir (asıl iddia bu)
        fark = (oracle["citation"]["recall_page"] - e2e["citation"]["recall_page"])
        self.assertIsInstance(fark, float)


class RunSignatureTests(unittest.TestCase):
    def test_run_rejects_bad_mode_before_any_work(self):
        with self.assertRaises(ValueError):
            R.run(mode="yok")

    def test_retrieval_only_does_not_require_api_key(self):
        """CI'da anahtar olmadan koşabilmeli — bu modun varlık sebebi."""
        import os
        from unittest import mock
        clean = {k: "" for k in ("LLM_API_KEY", "DEEPSEEK_API_KEY", "NVIDIA_API_KEY")}
        with mock.patch.dict(os.environ, clean):
            # anahtar yok: end_to_end RuntimeError, retrieval_only kitap yokluğunda
            # FileNotFoundError'a kadar ilerler (yani anahtar kapısını GEÇER)
            with self.assertRaises(RuntimeError):
                R.run(mode="end_to_end", book_path="/olmayan/kitap.pdf")
            with self.assertRaises(FileNotFoundError):
                R.run(mode="retrieval_only", book_path="/olmayan/kitap.pdf")


if __name__ == "__main__":
    unittest.main()
