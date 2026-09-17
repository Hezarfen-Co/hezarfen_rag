"""E2E (AUDIT EXP-007 #17) — tam zincir tek testte:
ingest(sentetik kanonik) → chunk → embed(GERÇEK BGE-M3) → index(dense+BM25+sparse)
→ retrieve(hibrit+kasa izolasyonu) → rerank(GERÇEK BGE-reranker) → generate(STUB
LLMClient, API maliyeti/anahtarı YOK) → atıflı cevap; + kasa izolasyon; + özet.

Gerçek retrieval/rerank modelleri yüklenir (yavaş) ama LLM stub'lanır → deterministik,
ücretsiz. Model yüklenemezse test atlanır (CI/ortam güvenliği)."""
import unittest

import corpus

from src.pricing import Usage


def _units():
    from src.ingest.canonical import CanonicalUnit
    def u(sid, page, text):
        return CanonicalUnit(span_id=sid, doc_id="e2e", sinif="12", ders="biyoloji",
                             kaynak_turu="ders_kitabi", page=page, bbox=(0, 0, 400, 500),
                             block_no=0, kind="paragraph", text=text, page_visual="mixed",
                             retrieval_disi=False)
    return [
        u("e2e#10.0", 10, "Mitokondri hücrenin enerji santralidir ve hücresel solunumla "
                          "ATP (enerji) üretir. Kendi DNA'sını taşır."),
        u("e2e#20.0", 20, "Ribozomlar protein sentezinin yapıldığı organellerdir; mRNA'daki "
                          "bilgiyi amino asit dizisine çevirir."),
        u("e2e#30.0", 30, "Kloroplast bitki hücrelerinde fotosentez yaparak ışık enerjisini "
                          "kimyasal enerjiye dönüştürür."),
        u("e2e#40.0", 40, "Hücre zarı seçici geçirgendir; madde giriş çıkışını düzenler."),
    ]


class _StubChat:
    def __init__(self, text): self.text = text; self.model = "deepseek-chat"; \
        self.usage = Usage(input_cache_miss=50, output=20); self.latency_s = 0.0
class _StubLLMClient:
    """Kaynak [1]'e atıf yapan sabit cevap (üretim LLM'i yerine)."""
    def __init__(self, text): self._t = text; self.model = "deepseek-chat"
    def chat(self, prompt, system=None, **k): return _StubChat(self._t)


def _build():
    from src.chunk import chunk_document
    from src.embed import BGEM3Embedder
    from src.index import DenseIndex, BM25Index
    from src.retrieve import SparseIndex, HybridRetriever
    from src.ingest.canonical import CanonicalDoc
    from src.generate import build_span_meta

    doc = CanonicalDoc(source_path="e2e", doc_id="e2e", source_version="v1", sinif="12",
                       ders="biyoloji", kaynak_turu="ders_kitabi", page_count=40, units=_units())
    children = [c for c in chunk_document(doc) if c.level == "child"]
    ids = [c.chunk_id for c in children]
    texts = [c.text for c in children]
    by_id = {c.chunk_id: c for c in children}
    emb = corpus.shared_embedder()
    _, vecs = emb.embed_chunks(children, batch_size=8)
    meta = {c.chunk_id: {"sinif": "12", "ders": "biyoloji"} for c in children}
    retr = HybridRetriever(emb, DenseIndex(dim=1024).build(ids, vecs),
                           BM25Index().build(ids, texts),
                           SparseIndex().build(ids, emb.embed_sparse(texts, batch_size=8)),
                           meta=meta)
    return doc, children, by_id, retr, build_span_meta(doc)


try:
    import torch  # noqa: F401
    from src.embed import BGEM3Embedder  # noqa: F401
    _CAN_RUN = True
except Exception:
    _CAN_RUN = False


@unittest.skipUnless(_CAN_RUN, "BGE/torch yok — e2e atlandı")
class PipelineE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.rerank import BGEReranker
        cls.doc, cls.children, cls.by_id, cls.retr, cls.span_meta = _build()
        cls.reranker = corpus.shared_reranker()

    def _gen(self, stub_text, role_ctx=None):
        from src.generate import Generator
        from src.guard.roles import RoleContext, Role
        if role_ctx is None:
            role_ctx = RoleContext(role=Role.STUDENT, sinif="12", ders_list=["biyoloji"])
        return Generator(self.retr, self.reranker, self.by_id, self.span_meta,
                         llm=_StubLLMClient(stub_text), ders="biyoloji",
                         role_ctx=role_ctx, cost_recorder=lambda **k: None)

    def test_grounded_answer_end_to_end(self):
        gen = self._gen("Mitokondri hücrede ATP (enerji) üretir [1].")
        res = gen.answer("Hücrede enerji nerede üretilir?", top_n=3, candidate_n=4)
        self.assertFalse(res.abstained)
        self.assertTrue(res.citations)                       # atıflı
        self.assertIn(10, res.citations[0]["pages"])         # doğru sayfaya (mitokondri) çözüldü
        self.assertGreater(res.cost_usd, 0.0)                # stub usage → maliyet

    def test_kasa_izolasyon_wrong_ders_abstains(self):
        from src.guard.roles import RoleContext, Role
        gen = self._gen("cevap [1].",
                        role_ctx=RoleContext(role=Role.STUDENT, sinif="12", ders_list=["kimya"]))
        res = gen.answer("Hücrede enerji nerede üretilir?", top_n=3, candidate_n=4)
        self.assertTrue(res.abstained)                       # biyoloji chunk'ı görmemeli
        self.assertEqual(res.reason, "insufficient_data")

    def test_summary_end_to_end(self):
        from src.summarize.scope import resolve_scope
        from src.summarize.summarizer import Summarizer
        units = resolve_scope(self.doc, pages=[10, 20])
        self.assertEqual(len(units), 2)
        s = Summarizer(llm=_StubLLMClient("Mitokondri enerji üretir [1]. Ribozom protein [2]."),
                       cost_recorder=lambda **k: None)
        res = s.summarize(units, scope_label="Organeller")
        self.assertFalse(res.abstained)
        self.assertTrue(res.citations)
        self.assertEqual(res.scope_pages, [10, 20])


if __name__ == "__main__":
    unittest.main()
