"""#2/D3 HTTP servisi testleri — FastAPI TestClient + stub RagService (model yok)."""
import unittest

try:
    from fastapi.testclient import TestClient
    from src.service.http_app import create_app
    _HAS_FASTAPI = True
except Exception:
    _HAS_FASTAPI = False


class _StubService:
    def __init__(self):
        self.last = {}
    def chat(self, req):
        self.last["chat"] = req
        return {"text": "Cevap [1].", "abstained": False, "reason": "",
                "citations": [{"n": 1, "pages": [10]}], "used_source_ids": ["c1"],
                "cost_usd": 0.001, "cache_hit": False}
    def summarize(self, req):
        self.last["summarize"] = req
        return {"text": "Özet.", "abstained": False, "reason": "", "citations": [],
                "scope_pages": [10, 11], "hierarchical": False, "cost_usd": 0.02}
    def generate_questions(self, req):
        self.last["questions"] = req
        return {"items": [{"soru": "s1", "cevap": "c1", "zorluk": "orta"}],
                "abstained": False, "reason": "", "span_ids": [], "pages": [10], "cost_usd": 0.01}


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class HttpAppTests(unittest.TestCase):
    def setUp(self):
        self.svc = _StubService()
        self.client = TestClient(create_app(self.svc))

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_chat(self):
        r = self.client.post("/rag/chat", json={
            "query": "DNA nedir", "role": {"role": "student", "sinif": "12",
                                           "ders_list": ["biyoloji"]}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["text"], "Cevap [1].")
        self.assertEqual(self.svc.last["chat"]["query"], "DNA nedir")
        self.assertEqual(self.svc.last["chat"]["role"]["role"], "student")

    def test_chat_validation_missing_query(self):
        r = self.client.post("/rag/chat", json={"role": {"role": "student"}})
        self.assertEqual(r.status_code, 422)          # query zorunlu

    def test_summarize(self):
        r = self.client.post("/rag/summarize", json={"scope": {"pages": [10, 11]}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["scope_pages"], [10, 11])

    def test_questions(self):
        r = self.client.post("/rag/questions", json={"scope": {"pages": [10]}, "n": 3})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["items"]), 1)
        self.assertEqual(self.svc.last["questions"]["n"], 3)


if __name__ == "__main__":
    unittest.main()
