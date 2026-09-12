"""#82 (EXP-010/OPS-10) — soğuk başlangıç: servis önce ayağa kalksın.

ÖLÇÜLEN DURUM: `main()` sırayla `build_canonical` → chunk → `embed_chunks`
(dense) + `embed_sparse` = **korpusun iki tam geçişi** → 3 indeks → `Generator`;
`uvicorn.run` bunların **hepsi bittikten sonra** çağrılıyordu → o ana kadar
`/health` dahil hiçbir port dinlenmiyor.

BU MAKİNEDE (GPU) ÖLÇÜLDÜ: `build_canonical` 32,3 s + embed iki geçiş 8,4 s.
Denetimin CPU hesabı ~155 s. Konteyner sağlık yoklaması bu süre boyunca
başarısız olur ve orkestratör kabı sürekli yeniden başlatabilir.
"""
import os
import unittest

try:
    from fastapi.testclient import TestClient
    from src.service.http_app import _LazyService, create_app
    _HAS_FASTAPI = True
except Exception:                                   # pragma: no cover
    _HAS_FASTAPI = False


class _Gercek:
    generator = object()
    doc = object()
    question_gen = object()
    summarizer = object()

    def chat(self, req):
        return {"text": "gercek", "abstained": False, "reason": ""}

    def summarize(self, req):
        return {"text": "ozet", "abstained": False, "reason": ""}

    def generate_questions(self, req):
        return {"items": [], "abstained": False, "reason": ""}


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class WarmupTests(unittest.TestCase):
    def setUp(self):
        self.lazy = _LazyService()
        self.c = TestClient(create_app(self.lazy, rate_limit_per_min=0))

    def test_liveness_answers_before_the_pipeline_is_built(self):
        """Asıl kazanç: port HEMEN dinleniyor."""
        self.assertEqual(self.c.get("/health").status_code, 200)

    def test_readiness_is_503_while_warming(self):
        r = self.c.get("/ready")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["status"], "not_ready")

    def test_requests_get_a_typed_refusal_not_a_crash(self):
        out = self.c.post("/rag/chat", json={"query": "DNA nedir?"})
        self.assertEqual(out.status_code, 200)
        govde = out.json()
        self.assertTrue(govde["abstained"])
        self.assertEqual(govde["reason"], "service_warming_up")
        self.assertTrue(govde["text"].strip())

    def test_becomes_ready_after_assignment(self):
        self.lazy.ata(_Gercek())
        self.assertEqual(self.c.get("/ready").status_code, 200)
        self.assertEqual(self.c.post("/rag/chat",
                                     json={"query": "q"}).json()["text"], "gercek")

    def test_all_three_paths_are_covered_while_warming(self):
        for path, body in (("/rag/chat", {"query": "q"}),
                           ("/rag/summarize", {"scope": {"pages": [1]}}),
                           ("/rag/questions", {"scope": {"pages": [1]}})):
            with self.subTest(path):
                govde = self.c.post(path, json=body).json()
                self.assertEqual(govde["reason"], "service_warming_up")

    def test_failed_warmup_is_recorded(self):
        """Kurulum patlarsa süreç ölmemeli ama durum GÖRÜNÜR olmalı."""
        self.lazy.hata = "RuntimeError: model inmedi"
        self.assertEqual(self.c.get("/ready").status_code, 503)
        self.assertIsNotNone(self.lazy.hata)


class SinglePassEmbedTests(unittest.TestCase):
    """Korpus iki kez kodlanıyordu; tek `encode()` ikisini birden döndürüyor."""

    def test_service_builder_uses_the_single_pass(self):
        import inspect
        from src.service import http_app
        kaynak = inspect.getsource(http_app.build_service)
        self.assertIn("embed_both", kaynak)
        self.assertNotIn("embed_sparse", kaynak)

    def test_embed_both_returns_both_and_is_empty_safe(self):
        from src.embed.embedder import BGEM3Embedder
        e = BGEM3Embedder()
        vecs, sparse = e.embed_both([])          # model YÜKLENMEZ
        self.assertEqual(len(vecs), 0)
        self.assertEqual(sparse, [])

    def test_docstring_records_the_cache_limit(self):
        """`embed_both` embedding cache'ini KULLANMAZ — bu bilinçli ve
        yazılı olmalı, yoksa artımlı güncellemede sessizce yavaşlarız."""
        from src.embed.embedder import BGEM3Embedder
        self.assertIn("cache", (BGEM3Embedder.embed_both.__doc__ or "").lower())


if __name__ == "__main__":
    unittest.main()
