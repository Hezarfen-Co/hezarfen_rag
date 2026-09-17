"""#50 (+#48) — HTTP servis sertleştirmesi.

NEDEN (EXP-010/SEC-09 + OPS-13, TestClient ile ÖLÇÜLMÜŞTÜ):
- `/health` dahil hiçbir uçta kimlik doğrulama yok, oran sınırı yok
- `/docs`, `/redoc`, `/openapi.json` **açık**
- 2 MB `query`, `top_n=1e9`, `/rag/questions n=1e6`, 500 turlu ~50 MB `history`
  → hepsi **HTTP 200**; `top_n='abc'` → yakalanmamış `ValueError` → **500**
- `/health` servis bozuk olsa da `{"status":"ok"}`
- `request_id` yok; yakalanmamış hata çıplak `"Internal Server Error"` döndürüyor,
  backend `abstained/reason` sözleşmesine göre yazıldığı için parse edemiyor

`top_n`/`candidate_n` doğrudan retrieval ve prompt genişliğine gittiği için bu
aynı zamanda bir **maliyet amplifikasyonu** yoluydu (OPS-05).

DÜRÜST SINIR: oran sınırı süreç-içidir; çok-worker/çok-pod dağıtımda gerçek sınır
ters vekilde ya da paylaşımlı sayaçta olmalı. Buradaki amaç tek bir istemcinin
servisi tek başına düşürmesini zorlaştırmak.
"""
import unittest

try:
    from fastapi.testclient import TestClient
    from src.service.http_app import create_app
    _HAS_FASTAPI = True
except Exception:                                   # pragma: no cover
    _HAS_FASTAPI = False


class _Service:
    generator = object()
    doc = object()
    question_gen = object()

    def chat(self, req):
        return {"text": "ok", "abstained": False, "reason": ""}

    def summarize(self, req):
        return {"text": "ok", "abstained": False, "reason": ""}

    def generate_questions(self, req):
        return {"items": [], "abstained": False, "reason": ""}


class _Exploding(_Service):
    def chat(self, req):
        raise RuntimeError("DeepSeek 429 Too Many Requests")


def _client(**kw):
    kw.setdefault("rate_limit_per_min", 0)      # testlerde sınır kapalı
    return TestClient(create_app(_Service(), **kw))


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class RequestBoundsTests(unittest.TestCase):
    """Ölçülen 5 kabul edilen kötü istek artık reddedilmeli."""

    def setUp(self):
        self.c = _client()

    def test_query_over_field_limit_rejected(self):
        """Govde sinirinin ALTINDA ama alan sinirinin USTUNDE -> Pydantic 422."""
        r = self.c.post("/rag/chat", json={"query": "A" * 5000})
        self.assertEqual(r.status_code, 422)

    def test_oversized_query_rejected_before_parsing(self):
        """2 MB govde artik AYRISTIRILMADAN once 413 ile reddedilir."""
        r = self.c.post("/rag/chat", json={"query": "A" * 2_000_000})
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.json()["reason"], "payload_too_large")

    def test_absurd_top_n_rejected(self):
        r = self.c.post("/rag/chat",
                        json={"query": "q", "options": {"top_n": 10 ** 9}})
        self.assertEqual(r.status_code, 422)

    def test_absurd_candidate_n_rejected(self):
        r = self.c.post("/rag/chat",
                        json={"query": "q", "options": {"candidate_n": 10 ** 9}})
        self.assertEqual(r.status_code, 422)

    def test_absurd_question_count_rejected(self):
        r = self.c.post("/rag/questions",
                        json={"scope": {"pages": [1]}, "n": 10 ** 6})
        self.assertEqual(r.status_code, 422)

    def test_huge_history_rejected(self):
        hist = [{"role": "user", "content": "x"}] * 500
        r = self.c.post("/rag/chat", json={"query": "q", "history": hist})
        self.assertEqual(r.status_code, 422)

    def test_oversized_scope_span_ids_rejected(self):
        r = self.c.post("/rag/summarize",
                        json={"scope": {"span_ids": [f"d#1.{i}" for i in range(2000)]}})
        self.assertIn(r.status_code, (413, 422))

    def test_non_numeric_top_n_is_422_not_500(self):
        """Eskiden yakalanmamış ValueError → 500 dönüyordu."""
        r = self.c.post("/rag/chat",
                        json={"query": "q", "options": {"top_n": "abc"}})
        self.assertEqual(r.status_code, 422)

    def test_empty_query_rejected(self):
        self.assertEqual(self.c.post("/rag/chat", json={"query": ""}).status_code, 422)

    def test_oversized_scope_page_list_rejected(self):
        r = self.c.post("/rag/summarize",
                        json={"scope": {"pages": list(range(1, 5000))}})
        self.assertEqual(r.status_code, 422)

    def test_oversized_scope_label_rejected(self):
        r = self.c.post("/rag/summarize",
                        json={"scope": {"pages": [1], "scope_label": "A" * 5000}})
        self.assertEqual(r.status_code, 422)

    def test_normal_request_still_works(self):
        r = self.c.post("/rag/chat",
                        json={"query": "DNA nedir?", "options": {"top_n": 6}})
        self.assertEqual(r.status_code, 200)


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class DocsExposureTests(unittest.TestCase):
    def test_docs_closed_by_default(self):
        c = _client()
        for path in ("/docs", "/redoc", "/openapi.json"):
            with self.subTest(path):
                self.assertEqual(c.get(path).status_code, 404)

    def test_docs_can_be_opened_explicitly(self):
        c = _client(expose_docs=True)
        self.assertEqual(c.get("/openapi.json").status_code, 200)


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class HealthReadyTests(unittest.TestCase):
    def test_health_is_liveness_only(self):
        self.assertEqual(_client().get("/health").status_code, 200)

    def test_ready_reports_not_ready_when_generator_missing(self):
        """Eskiden `/health` servis BOZUK olsa da `ok` diyordu."""
        class _Broken(_Service):
            generator = None
        c = TestClient(create_app(_Broken(), rate_limit_per_min=0))
        r = c.get("/ready")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["status"], "not_ready")

    def test_ready_reports_capabilities(self):
        body = _client().get("/ready").json()
        self.assertTrue(body["ozet"])
        self.assertTrue(body["soru"])


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class AuthTests(unittest.TestCase):
    def test_auth_disabled_by_default(self):
        """Geriye uyum: token verilmemişse davranış değişmez."""
        self.assertEqual(_client().post("/rag/chat",
                                        json={"query": "q"}).status_code, 200)

    def test_token_required_when_configured(self):
        c = _client(service_token="gizli")
        self.assertEqual(c.post("/rag/chat", json={"query": "q"}).status_code, 401)

    def test_wrong_token_rejected(self):
        c = _client(service_token="gizli")
        r = c.post("/rag/chat", json={"query": "q"},
                   headers={"X-Service-Token": "yanlis"})
        self.assertEqual(r.status_code, 401)

    def test_correct_token_accepted(self):
        c = _client(service_token="gizli")
        r = c.post("/rag/chat", json={"query": "q"},
                   headers={"X-Service-Token": "gizli"})
        self.assertEqual(r.status_code, 200)

    def test_all_rag_paths_are_protected(self):
        c = _client(service_token="gizli")
        for path, body in (("/rag/chat", {"query": "q"}),
                           ("/rag/summarize", {"scope": {"pages": [1]}}),
                           ("/rag/questions", {"scope": {"pages": [1]}})):
            with self.subTest(path):
                self.assertEqual(c.post(path, json=body).status_code, 401)

    def test_health_stays_open_for_probes(self):
        """Liveness probe'u token taşıyamaz — açık kalmalı."""
        c = _client(service_token="gizli")
        self.assertEqual(c.get("/health").status_code, 200)


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class RateLimitTests(unittest.TestCase):
    def test_limit_blocks_after_threshold(self):
        c = TestClient(create_app(_Service(), rate_limit_per_min=3))
        codes = [c.post("/rag/chat", json={"query": "q"}).status_code
                 for _ in range(5)]
        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(codes[3:], [429, 429])

    def test_retry_after_header_present(self):
        c = TestClient(create_app(_Service(), rate_limit_per_min=1))
        c.post("/rag/chat", json={"query": "q"})
        r = c.post("/rag/chat", json={"query": "q"})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.headers.get("Retry-After"), "60")

    def test_zero_disables_limit(self):
        c = TestClient(create_app(_Service(), rate_limit_per_min=0))
        for _ in range(30):
            self.assertEqual(c.post("/rag/chat",
                                    json={"query": "q"}).status_code, 200)


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class ErrorContractTests(unittest.TestCase):
    def test_unhandled_error_returns_typed_contract_not_bare_500(self):
        """OPS-06: stub 429 → gövde `"Internal Server Error"` dönüyordu ve
        backend `abstained/reason` sözleşmesine göre parse edemiyordu."""
        c = TestClient(create_app(_Exploding(), rate_limit_per_min=0),
                       raise_server_exceptions=False)
        r = c.post("/rag/chat", json={"query": "q"})
        self.assertEqual(r.status_code, 503)
        body = r.json()
        self.assertTrue(body["abstained"])
        self.assertEqual(body["reason"], "service_unavailable")
        self.assertIn("citations", body)
        self.assertTrue(body["text"])                  # kullanıcıya Türkçe mesaj
        self.assertIn("request_id", body)

    def test_unhandled_error_is_also_logged_with_its_cause(self):
        """SESSİZ 503: tipli gövde tek başına yetmez — operatör nedeni logdan
        görebilmeli (canlıda iki 503 logda HİÇ iz bırakmadı)."""
        import contextlib
        import io
        err = io.StringIO()
        c = TestClient(create_app(_Exploding(), rate_limit_per_min=0),
                       raise_server_exceptions=False)
        with contextlib.redirect_stderr(err):
            r = c.post("/rag/chat", json={"query": "q"})
        self.assertEqual(r.status_code, 503)
        iz = err.getvalue()
        self.assertIn("[http][HATA]", iz)
        self.assertIn("RuntimeError", iz)         # hata TÜRÜ logda
        self.assertIn("429", iz)                  # nedeni taşıyan mesaj logda

    def test_request_id_header_on_success(self):
        r = _client().post("/rag/chat", json={"query": "q"})
        self.assertTrue(r.headers.get("X-Request-Id"))

    def test_client_request_id_is_echoed(self):
        r = _client().post("/rag/chat", json={"query": "q"},
                           headers={"X-Request-Id": "izlenebilir-123"})
        self.assertEqual(r.headers.get("X-Request-Id"), "izlenebilir-123")


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class BodyLimitTests(unittest.TestCase):
    """Ham govde siniri: Pydantic alan sinirlari govde AYRISTIRILDIKTAN sonra
    calisir; 50 MB'lik bir JSON once tamamen okunup parse edilirdi."""

    def test_content_length_header_is_enforced(self):
        c = _client(max_body_bytes=1000)
        r = c.post("/rag/chat", content=b"x" * 5000,
                   headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)

    def test_chunked_body_without_content_length_is_enforced(self):
        """`Content-Length` basligina GUVENILMEZ: chunked aktarimda gelmez.
        Bu yuzden okunan bayt AKIS UZERINDE sayilir."""
        def _parcali():
            for _ in range(20):
                yield b"x" * 500
        c = _client(max_body_bytes=1000)
        r = c.post("/rag/chat", content=_parcali(),
                   headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)

    def test_error_body_follows_the_contract(self):
        c = _client(max_body_bytes=100)
        body = c.post("/rag/chat", json={"query": "A" * 500}).json()
        self.assertTrue(body["abstained"])
        self.assertEqual(body["reason"], "payload_too_large")
        self.assertEqual(body["citations"], [])

    def test_normal_body_passes(self):
        c = _client(max_body_bytes=256 * 1024)
        self.assertEqual(c.post("/rag/chat", json={"query": "q"}).status_code, 200)

    def test_zero_disables_the_limit(self):
        c = _client(max_body_bytes=0)
        r = c.post("/rag/chat", json={"query": "A" * 5000})
        self.assertEqual(r.status_code, 422)      # artik yalniz alan siniri


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class DeadlineTests(unittest.TestCase):
    def test_slow_request_returns_typed_504(self):
        """Bir LLM cagrisi asilirsa istek sonsuza kadar asili kalmamali."""
        class _Slow(_Service):
            def chat(self, req):
                import time
                time.sleep(0.5)
                return {"text": "gec", "abstained": False, "reason": ""}

        c = TestClient(create_app(_Slow(), rate_limit_per_min=0,
                                  request_timeout_s=0.05))
        r = c.post("/rag/chat", json={"query": "q"})
        self.assertEqual(r.status_code, 504)
        body = r.json()
        self.assertTrue(body["abstained"])
        self.assertEqual(body["reason"], "timeout")
        self.assertIn("request_id", body)

    def test_fast_request_unaffected(self):
        c = TestClient(create_app(_Service(), rate_limit_per_min=0,
                                  request_timeout_s=5.0))
        self.assertEqual(c.post("/rag/chat", json={"query": "q"}).status_code, 200)

    def test_zero_disables_the_deadline(self):
        c = TestClient(create_app(_Service(), rate_limit_per_min=0,
                                  request_timeout_s=0))
        self.assertEqual(c.post("/rag/chat", json={"query": "q"}).status_code, 200)


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class HostAndCorsTests(unittest.TestCase):
    def test_untrusted_host_rejected_when_configured(self):
        c = TestClient(create_app(_Service(), rate_limit_per_min=0,
                                  allowed_hosts=["rag.ic-ag"]))
        self.assertEqual(c.post("/rag/chat", json={"query": "q"}).status_code, 400)

    def test_trusted_host_passes(self):
        c = TestClient(create_app(_Service(), rate_limit_per_min=0,
                                  allowed_hosts=["testserver"]))
        self.assertEqual(c.post("/rag/chat", json={"query": "q"}).status_code, 200)

    def test_wildcard_keeps_backward_compatibility(self):
        c = TestClient(create_app(_Service(), rate_limit_per_min=0,
                                  allowed_hosts=["*"]))
        self.assertEqual(c.post("/rag/chat", json={"query": "q"}).status_code, 200)

    def test_cors_closed_by_default(self):
        """Basligi HIC gondermemek en guvenli varsayilan: tarayici capraz-kaynak
        cagriyi kendisi reddeder."""
        r = _client().post("/rag/chat", json={"query": "q"},
                           headers={"Origin": "https://kotu.example"})
        self.assertIsNone(r.headers.get("access-control-allow-origin"))

    def test_cors_only_for_declared_origin(self):
        c = TestClient(create_app(_Service(), rate_limit_per_min=0,
                                  cors_origins=["https://hezarfen.example"]))
        ok = c.post("/rag/chat", json={"query": "q"},
                    headers={"Origin": "https://hezarfen.example"})
        self.assertEqual(ok.headers.get("access-control-allow-origin"),
                         "https://hezarfen.example")
        kotu = c.post("/rag/chat", json={"query": "q"},
                      headers={"Origin": "https://kotu.example"})
        self.assertIsNone(kotu.headers.get("access-control-allow-origin"))


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class ConfigVisibilityTests(unittest.TestCase):
    def test_ready_reports_which_brakes_are_on(self):
        c = TestClient(create_app(_Service(), service_token="gizli",
                                  rate_limit_per_min=30, max_body_bytes=1234,
                                  request_timeout_s=45, allowed_hosts=["testserver"],
                                  cors_origins=[]))
        g = c.get("/ready").json()["guvenlik"]
        self.assertTrue(g["token"])
        self.assertEqual(g["oran_limiti"], 30)
        self.assertEqual(g["govde_siniri"], 1234)
        self.assertEqual(g["son_tarih_s"], 45)
        self.assertFalse(g["docs_acik"])
        self.assertTrue(g["host_siniri"])
        self.assertFalse(g["cors"])

    def test_secret_value_is_never_exposed(self):
        c = TestClient(create_app(_Service(), service_token="cok-gizli-sir",
                                  rate_limit_per_min=0))
        self.assertNotIn("cok-gizli-sir", c.get("/ready").text)

    def test_unsafe_defaults_are_announced_at_startup(self):
        """Varsayilanlar geriye uyumlu (korumasiz) -- ama SESSIZ olmamali."""
        import importlib
        from unittest import mock
        from src.service import http_app as m
        with mock.patch.dict("os.environ", {"RAG_SERVICE_TOKEN": "",
                                            "RAG_ALLOWED_HOSTS": "*"}, clear=False):
            m2 = importlib.reload(m)
            try:
                u = " ".join(m2._yapilandirma_uyarilari())
                self.assertIn("RAG_SERVICE_TOKEN", u)
                self.assertIn("RAG_ALLOWED_HOSTS", u)
            finally:
                importlib.reload(m)


if __name__ == "__main__":
    unittest.main()
