"""Faz — Backend-hazır HTTP servisi (#2/D3). RagService'i (transport-bağımsız iş
mantığı) FastAPI ile sarar: API-CONTRACT.md'deki /rag/chat + /rag/summarize +
/rag/questions + /health. Backend bu HTTP'yi çağırır (o da front'a döner) — böylece
RAG repo'su "backend'e hazır" olur; backend/front'a bu repodan DOKUNULMAZ.

GÜVENLİK: `role` istek gövdesinde gelir ve SUNUCU-TARAFI türetilmiş kabul edilir —
gerçek üretimde bu HTTP servisi backend'in ARKASINDA (iç ağ) çalışır ve role'ü
backend'in auth katmanı doldurur; servis onu doğrulamaz (RES-002/003).

Çalıştırma:  python -m src.service.http_app   (env: BOOK_PATH, SINIF, DERS)
Test:        create_app(stub_service) + fastapi.testclient.TestClient  (model gerekmez)
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

# NOT: fastapi import'lari MODUL DUZEYINDE olmak ZORUNDA. `from __future__ import
# annotations` ile tum anotasyonlar STRING olur ve FastAPI bunlari modulun global
# ad uzayinda cozer; `Request` fonksiyon icinde import edilirse cozemez ve
# parametreyi query-param sanip 422 doner (bu hata #50'de gercekten olustu).


# #50/#48 (EXP-010/SEC-09 + OPS-13) -- ISTEK SINIRLARI.
# Olculmustu: 2 MB `query`, `top_n=1e9`, `/rag/questions n=1e6`, 500 turlu ~50 MB
# `history` -> hepsi HTTP 200 aliyordu; `top_n='abc'` yakalanmamis ValueError ile
# 500 donuyordu. `top_n`/`candidate_n` dogrudan retrieval ve prompt genisligine
# gittigi icin bu bir MALIYET AMPLIFIKASYONU yoluydu.
MAX_QUERY_CHARS = 2000
MAX_HISTORY_TURNS = 20
MAX_HISTORY_CHARS = 20_000
MAX_SCOPE_PAGES = 200
MAX_SPAN_IDS = 500


class RoleModel(BaseModel):
    role: str = Field(max_length=32)
    sinif: str | None = Field(default=None, max_length=16)
    ders_list: list[str] = Field(default_factory=list, max_length=64)


class ChatOptions(BaseModel):
    """Eskiden serbest `dict`ti ve `int(opts.get(...))` ile handler'a geciyordu."""
    top_n: int = Field(default=6, ge=1, le=20)
    candidate_n: int = Field(default=40, ge=1, le=200)
    ders: str | None = Field(default=None, max_length=64)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    history: list[dict] | None = Field(default=None, max_length=MAX_HISTORY_TURNS)
    role: RoleModel | None = None
    options: ChatOptions = Field(default_factory=ChatOptions)


class ScopeModel(BaseModel):
    pages: list[int] | None = Field(default=None, max_length=MAX_SCOPE_PAGES)
    span_ids: list[str] | None = Field(default=None, max_length=MAX_SPAN_IDS)
    ders: str | None = Field(default=None, max_length=64)
    sinif: str | None = Field(default=None, max_length=16)
    scope_label: str = Field(default="", max_length=200)


class SummarizeRequest(BaseModel):
    scope: ScopeModel
    role: RoleModel | None = None


class QuestionsRequest(BaseModel):
    scope: ScopeModel
    role: RoleModel | None = None
    n: int = Field(default=5, ge=1, le=20)
    difficulty: str = Field(default="orta", max_length=16)
    seed_question: str | None = Field(default=None, max_length=500)


# #50 (EXP-010/SEC-09 + OPS-13) -- SERVIS SERTLESTIRME.
# Olculmustu: `/health` dahil hicbir ucta kimlik yok; oran siniri yok;
# `/docs`,`/redoc`,`/openapi.json` ACIK; CORS/TrustedHost yok; `/health` servis
# bozuk olsa da `ok` donuyor; `request_id` yok. Tasarim geregi servis backend'in
# ARKASINDA calisiyor -- ama savunma derinligi SIFIRDI: yanlislikla disa acilirsa
# ya da backend ele gecerse hicbir fren yok.
SERVICE_TOKEN = os.environ.get("RAG_SERVICE_TOKEN") or None   # None -> auth KAPALI
EXPOSE_DOCS = os.environ.get("RAG_EXPOSE_DOCS", "0") not in ("0", "", "false", "False")
RATE_LIMIT_PER_MIN = int(os.environ.get("RAG_RATE_LIMIT_PER_MIN", "60"))

# Ham govde siniri: Pydantic alan sinirlari govde AYRISTIRILDIKTAN sonra calisir,
# yani 50 MB'lik bir JSON once tamamen okunur ve parse edilir (bellek + CPU).
# Bu sinir okuma sirasinda, ayristirmadan ONCE uygulanir.
MAX_BODY_BYTES = int(os.environ.get("RAG_MAX_BODY_BYTES", str(256 * 1024)))
# Istek basina son tarih: bir LLM cagrisi asilirsa istek sonsuza kadar asili kalmasin.
REQUEST_TIMEOUT_S = float(os.environ.get("RAG_REQUEST_TIMEOUT_S", "60"))
# Host ve CORS. CORS varsayilan KAPALI: basligi hic gondermemek en guvenli
# varsayilandir (tarayici capraz-kaynak cagriyi zaten reddeder).
ALLOWED_HOSTS = [h.strip() for h in
                 os.environ.get("RAG_ALLOWED_HOSTS", "*").split(",") if h.strip()]
CORS_ORIGINS = [o.strip() for o in
                os.environ.get("RAG_CORS_ORIGINS", "").split(",") if o.strip()]
# Kapanis: uvicorn'a verilir; ucusta olan istekler bitirilir.
GRACEFUL_SHUTDOWN_S = float(os.environ.get("RAG_GRACEFUL_SHUTDOWN_S", "20"))


class _BodyLimit:
    """Ham govde boyutu siniri (saf ASGI ara katmani).

    NEDEN BaseHTTPMiddleware DEGIL: govdeyi ayristirmadan ONCE, okuma akisi
    uzerinde saymak gerekiyor. `Content-Length` basligina GUVENILMEZ -- chunked
    aktarimda bu baslik hic gelmez. Bu yuzden hem baslik kontrol edilir hem de
    `receive` sarilarak gercekten okunan bayt sayilir; sinir asilirsa 413 doner.
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.max_bytes <= 0:
            await self.app(scope, receive, send)
            return
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    if int(v) > self.max_bytes:
                        await self._reddet(send)
                        return
                except ValueError:
                    pass
        okunan = 0
        asildi = False
        cevap_verildi = False

        async def _receive():
            # OLCULMUSTU: burada bir istisna FIRLATMAK ise yaramiyor -- FastAPI
            # govde ayristirma hatalarini yakalayip 400 "There was an error
            # parsing the body" donuyor, yani gercek sebep KAYBOLUYOR. Bu yuzden
            # akis kesilir (disconnect) ve 413 cevabini ara katman kendisi yazar.
            nonlocal okunan, asildi
            msg = await receive()
            if msg["type"] == "http.request":
                okunan += len(msg.get("body", b""))
                if okunan > self.max_bytes:
                    asildi = True
                    return {"type": "http.disconnect"}
            return msg

        async def _send(msg):
            nonlocal cevap_verildi
            if not asildi:
                await send(msg)
                return
            if msg["type"] == "http.response.start" and not cevap_verildi:
                cevap_verildi = True
                await self._reddet(send)
            # sinir asildiktan sonra asagidan gelen govde yutulur

        try:
            await self.app(scope, _receive, _send)
        except Exception:
            if not asildi:
                raise            # gercek hatalar yukariya, tipli cevaba gitsin
        if asildi and not cevap_verildi:
            cevap_verildi = True
            await self._reddet(send)

    @staticmethod
    async def _reddet(send):
        import json as _json
        govde = _json.dumps({"text": "İstek gövdesi çok büyük.", "abstained": True,
                             "reason": "payload_too_large", "citations": [],
                             "used_source_ids": [], "cost_usd": 0.0,
                             "cache_hit": False}, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(govde)).encode())]})
        await send({"type": "http.response.body", "body": govde})


class _RateLimiter:
    """Cok basit, surec-ici kayan pencere sayaci.

    DURUST SINIR: tek surec icinde calisir; cok-worker/cok-pod dagitimda gercek
    bir sinir DEGILDIR (oradaki dogru yer ters vekil ya da paylasimli sayac).
    Amaci tek bir istemcinin servisi tek basina dusurmesini zorlastirmak ve
    maliyet amplifikasyonunu (OPS-05) frenlemek."""

    def __init__(self, per_min: int):
        self.per_min = per_min
        self._hits: dict[str, list[float]] = {}
        self._lock = __import__("threading").Lock()

    def allow(self, key: str) -> bool:
        if self.per_min <= 0:
            return True
        now = __import__("time").time()
        with self._lock:
            q = [t for t in self._hits.get(key, []) if now - t < 60.0]
            if len(q) >= self.per_min:
                self._hits[key] = q
                return False
            q.append(now)
            self._hits[key] = q
            # bellek sizintisi olmasin: seyrek temizlik
            if len(self._hits) > 10_000:
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 120]:
                    self._hits.pop(k, None)
            return True


def create_app(service, *, service_token: str | None = None,
               rate_limit_per_min: int | None = None, expose_docs: bool | None = None,
               max_body_bytes: int | None = None, request_timeout_s: float | None = None,
               allowed_hosts: list[str] | None = None,
               cors_origins: list[str] | None = None):
    """RagService'i saran FastAPI uygulaması. `service` enjekte edilir (test'te stub;
    üretimde build_service()). Model yüklemez — yalnız HTTP↔handler eşlemesi.

    Guvenlik parametreleri env'den varsayilan alir; test/cagri yerinde ezilebilir.
    `service_token` verilmisse TUM `/rag/*` uclari `X-Service-Token` ister."""
    import uuid

    token = service_token if service_token is not None else SERVICE_TOKEN
    docs_on = EXPOSE_DOCS if expose_docs is None else expose_docs
    limiter = _RateLimiter(RATE_LIMIT_PER_MIN if rate_limit_per_min is None
                           else rate_limit_per_min)
    body_cap = MAX_BODY_BYTES if max_body_bytes is None else max_body_bytes
    deadline = REQUEST_TIMEOUT_S if request_timeout_s is None else request_timeout_s
    hosts = ALLOWED_HOSTS if allowed_hosts is None else allowed_hosts
    origins = CORS_ORIGINS if cors_origins is None else cors_origins

    app = FastAPI(title="Hezarfen RAG", version="1.0",
                  description="Kaynakla-konuşma + kanıtlı özet + benzer-soru (API-CONTRACT.md)",
                  # #50: uretimde API semasi disari acilmaz
                  docs_url="/docs" if docs_on else None,
                  redoc_url="/redoc" if docs_on else None,
                  openapi_url="/openapi.json" if docs_on else None)

    def _tipli_hata(status: int, reason: str, metin: str, rid: str) -> JSONResponse:
        """API-CONTRACT sozlesmesi: backend her durumda ayni alanlari bekler."""
        return JSONResponse(
            status_code=status,
            content={"text": metin, "abstained": True, "reason": reason,
                     "citations": [], "used_source_ids": [], "cost_usd": 0.0,
                     "cache_hit": False, "request_id": rid},
            headers={"X-Request-Id": rid})

    @app.middleware("http")
    async def _request_id_and_errors(request: Request, call_next):
        """#50: her istege `request_id`; yakalanmamis hata CIPLAK 500 yerine
        API-CONTRACT'a uygun tipli cevaba cevrilir (OPS-06: stub 429 -> govde
        `"Internal Server Error"` doonuyordu, backend bunu parse edemiyordu).
        Ayrica istek basina SON TARIH uygulanir.

        DURUST SINIR: uc noktalar senkron `def` oldugu icin thread havuzunda
        kosar; zaman asimi istemciye zamaninda bir cevap DONER ama arkadaki
        thread'i iptal ETMEZ (Python'da bir thread disaridan kesilemez). Gercek
        iptal saglayici katmaninda timeout ile olur -- DeepSeek istemcisinde
        `timeout=120` zaten var; buradaki sinir ondan KISA tutulmali."""
        import asyncio
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        try:
            if deadline > 0:
                resp = await asyncio.wait_for(call_next(request), timeout=deadline)
            else:
                resp = await call_next(request)
        except (asyncio.TimeoutError, TimeoutError):
            return _tipli_hata(504, "timeout",
                               "Cevap zamaninda hazir olmadi, tekrar dener misin?", rid)
        except Exception:
            return _tipli_hata(503, "service_unavailable",
                               "Şu anda cevap üretemiyorum, biraz sonra tekrar dene.", rid)
        resp.headers["X-Request-Id"] = rid
        return resp

    # NOT: ara katman sirasi TERSTEN kurulur -- en son eklenen EN DISTA calisir.
    # Istenen sira (distan ice): TrustedHost -> CORS -> govde siniri -> request_id.
    if body_cap > 0:
        app.add_middleware(_BodyLimit, max_bytes=body_cap)
    if origins:
        # Varsayilan KAPALI: baslik hic gonderilmezse tarayici capraz-kaynak
        # cagriyi zaten reddeder. Yalnizca acikca istenirse acilir.
        app.add_middleware(CORSMiddleware, allow_origins=origins,
                           allow_methods=["POST", "GET"],
                           allow_headers=["Content-Type", "X-Service-Token",
                                          "X-Request-Id"],
                           max_age=600)
    if hosts and hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    def _auth(x_service_token: str | None, request: Request) -> None:
        if token:
            import hmac
            if not x_service_token or not hmac.compare_digest(x_service_token, token):
                raise HTTPException(status_code=401, detail="service token gerekli")
        key = (x_service_token or "") + "|" + (request.client.host if request.client else "-")
        if not limiter.allow(key):
            raise HTTPException(status_code=429, detail="oran sınırı aşıldı",
                                headers={"Retry-After": "60"})

    @app.get("/health")
    def health():
        """Liveness: sürec ayakta mi. Hazir olup olmadigi `/ready`de."""
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        """#50: eskiden `/health` servis BOZUK olsa da `ok` donuyordu.
        Readiness ayri: generator/doc gercekten kurulu mu."""
        hazir = getattr(service, "generator", None) is not None
        return JSONResponse(status_code=200 if hazir else 503,
                            content={"status": "ready" if hazir else "not_ready",
                                     "ozet": getattr(service, "doc", None) is not None,
                                     "soru": getattr(service, "question_gen", None) is not None,
                                     # operator hangi frenlerin ACIK oldugunu
                                     # gorebilsin (sirrin KENDISI yazilmaz)
                                     "guvenlik": {"token": bool(token),
                                                  "oran_limiti": limiter.per_min,
                                                  "govde_siniri": body_cap,
                                                  "son_tarih_s": deadline,
                                                  "docs_acik": bool(docs_on),
                                                  "host_siniri": hosts != ["*"],
                                                  "cors": bool(origins)}})

    @app.post("/rag/chat")
    def chat(req: ChatRequest, request: Request,
             x_service_token: str | None = Header(default=None)):
        _auth(x_service_token, request)
        return service.chat(req.model_dump())

    @app.post("/rag/summarize")
    def summarize(req: SummarizeRequest, request: Request,
                  x_service_token: str | None = Header(default=None)):
        _auth(x_service_token, request)
        return service.summarize(req.model_dump())

    @app.post("/rag/questions")
    def questions(req: QuestionsRequest, request: Request,
                  x_service_token: str | None = Header(default=None)):
        _auth(x_service_token, request)
        return service.generate_questions(req.model_dump())

    return app


# M0-7 (#39): parent genisletme eval ile uretimde FARKLI davraniyordu (ACC-10).
# Tek anahtar: `RAG_INCLUDE_PARENTS` (varsayilan 0 = uretimin bugunku davranisi).
# eval/runner.py AYNI anahtari okur -> iki yol artik ayrisamaz. Hangi degerin
# dogru oldugu A/B ile karara baglanacak (#39 kabul kriteri).
INCLUDE_PARENTS_DEFAULT = os.environ.get("RAG_INCLUDE_PARENTS", "0") not in ("0", "", "false", "False")


def build_service(book_path: str, *, sinif: str, ders: str, corpus_version: str = "",
                  ocr: bool = False, vlm: bool = False,
                  include_parents: bool | None = None):
    """Gerçek pipeline'ı kurup RagService döndürür (ağır: PDF parse + BGE modelleri +
    indeks). main()/üretim için. corpus_version cache anahtarına girer (#30).

    `include_parents`: parent chunk'lar `chunks_by_id`'ye girsin mi (yani
    `rerank_select` parent genisletmesi ETKIN olsun mu). None -> env varsayilani."""
    if include_parents is None:
        include_parents = INCLUDE_PARENTS_DEFAULT
    from ..ingest.canonical import build_canonical
    from ..chunk import chunk_document
    from ..embed import BGEM3Embedder
    from ..index import DenseIndex, BM25Index
    from ..retrieve import SparseIndex, HybridRetriever
    from ..rerank import BGEReranker
    from ..generate import Generator, QuestionGenerator, build_span_meta
    from ..summarize.summarizer import Summarizer
    from ..guard.llm_classifier import LLMSafetyClassifier
    from .handler import RagService

    doc = build_canonical(book_path, sinif=sinif, ders=ders, ocr=ocr, vlm=vlm)
    cv = corpus_version or doc.source_version[:12]
    all_chunks = chunk_document(doc)
    children = [c for c in all_chunks if c.level == "child"]
    ids = [c.chunk_id for c in children]
    texts = [c.text for c in children]
    # M0-7 (#39) -- EXP-010/ACC-10: BU SATIR SESSIZ BIR AYRISMAYDI.
    # Eskiden `by_id` yalniz CHILD chunk'lari tasiyordu; `rerank_select`'teki
    # `ch.parent_id in chunks_by_id` kontrolu bu yuzden daima False oluyor ve
    # PARENT GENISLETME uretimde sessizce KAPALI kaliyordu. `src/eval/runner.py`
    # ise child+parent koyuyordu -> ACIK. Yani yayinlanmis 0.645/0.883 sayilari
    # uretimde kosan boru hattini TEMSIL ETMIYORDU.
    # Artik davranis TEK YERDEN, acikca secilir (ikisi ayni anahtari okur).
    # Varsayilan False = uretimin BUGUNKU davranisi; degistirmek icin A/B gerekiyor
    # (parent genisletme ACC-03'e gore atifi yanlis sayfaya kaydiriyor).
    by_id = ({c.chunk_id: c for c in all_chunks} if include_parents
             else {c.chunk_id: c for c in children})
    emb = BGEM3Embedder()
    # #82 (EXP-010/OPS-10): dense ve sparse TEK geçişte üretilir. Ayrı
    # çağrıldığında korpus iki kez kodlanıyordu. Gerçek kitapla ölçüldü
    # (10-biyoloji, 327 chunk, GPU): iki geçiş 8,4 s -> tek geçiş 3,9 s (%53).
    vecs, sparse = emb.embed_both(texts, batch_size=16)
    meta = {c.chunk_id: {"sinif": sinif, "ders": ders} for c in children}
    retr = HybridRetriever(emb, DenseIndex(dim=1024).build(ids, vecs),
                           BM25Index().build(ids, texts),
                           SparseIndex().build(ids, sparse),
                           meta=meta)
    span_meta = build_span_meta(doc)
    # #80/#82 — RERANKER'I DA ISIT. KONTEYNERDE KOSULARAK BULUNDU:
    # `build_service` embedder'i chunk'lari gomerek dolayli olarak yukluyor ama
    # reranker TEMBEL kaliyordu. `/ready` "hazir" diyor, ilk gercek soru gelince
    # reranker ~2 GB indirmeye kalkiyor ve istek son tarihini (60 s) asip
    # `reason="timeout"` donuyordu. Yani hazirlik sinyali YALAN soyluyordu.
    reranker = BGEReranker()
    reranker.warmup()
    gen = Generator(retr, reranker, by_id, span_meta, ders=ders,
                    safety_classifier=LLMSafetyClassifier(), context_packing=True,
                    corpus_version=cv, require_role=True)   # STRICT: rolsüz istek fail-closed
    return RagService(gen, doc=doc, summarizer=Summarizer(),
                      question_gen=QuestionGenerator(), ders=ders)


def _yapilandirma_uyarilari() -> list[str]:
    """#50: varsayilanlar GERIYE UYUMLU secildi (mevcut kurulum bozulmasin) ama
    bu, uretimde sessizce korumasiz kalmak anlamina gelmemeli. Acilista acikca
    soylenir; ayrica `/ready` bunlari makine-okunur bicimde raporlar."""
    u = []
    if not SERVICE_TOKEN:
        u.append("RAG_SERVICE_TOKEN yok → uçlar kimlik doğrulamasız (yalnız iç ağda çalıştır)")
    if ALLOWED_HOSTS == ["*"]:
        u.append("RAG_ALLOWED_HOSTS='*' → Host başlığı doğrulanmıyor")
    if EXPOSE_DOCS:
        u.append("RAG_EXPOSE_DOCS açık → /docs ve /openapi.json dışarıya açık")
    if RATE_LIMIT_PER_MIN <= 0:
        u.append("RAG_RATE_LIMIT_PER_MIN=0 → oran sınırı kapalı")
    return u


class _LazyService:
    """Henüz kurulmamış servisin yerine geçen taşıyıcı.

    #82 (EXP-010/OPS-10): `main()` önce bütün boru hattını kuruyor, `uvicorn`
    ondan SONRA çağrılıyordu → o ana kadar **hiçbir port dinlenmiyor**,
    `/health` bile cevap vermiyordu. Ölçülen soğuk başlangıç (bu makine, GPU):
    `build_canonical` 32,3 s + embed 8,4 s ≈ 41 s; CPU'da denetimin hesabıyla
    ~155 s. Konteyner sağlık yoklaması bu süre boyunca **başarısız** olur ve
    orkestratör kabı sürekli yeniden başlatabilir.

    Artık sunucu ÖNCE ayağa kalkar; boru hattı arka planda kurulur.
    `/health` (liveness) hemen 200, `/ready` (readiness) hazır olana dek 503
    döner — ikisinin ayrımı #50'de yapılmıştı, burada anlam kazanıyor.
    """

    def __init__(self):
        self.generator = None
        self.doc = None
        self.summarizer = None
        self.question_gen = None
        self._gercek = None
        self.hata: str | None = None

    def ata(self, service) -> None:
        self._gercek = service
        self.generator = service.generator
        self.doc = getattr(service, "doc", None)
        self.summarizer = getattr(service, "summarizer", None)
        self.question_gen = getattr(service, "question_gen", None)

    def _yonlendir(self, ad, req):
        if self._gercek is None:
            return {"text": "Servis hazırlanıyor, birazdan tekrar dener misin?",
                    "abstained": True, "reason": "service_warming_up",
                    "citations": [], "used_source_ids": [], "invalid_citations": [],
                    "cost_usd": 0.0, "cache_hit": False}
        return getattr(self._gercek, ad)(req)

    def chat(self, req):
        return self._yonlendir("chat", req)

    def summarize(self, req):
        return self._yonlendir("summarize", req)

    def generate_questions(self, req):
        return self._yonlendir("generate_questions", req)


def create_app_with_warmup():
    """uvicorn giriş noktası — sunucu HEMEN ayağa kalkar, boru hattı arka planda.

    Koşum:
        uvicorn src.service.http_app:create_app_with_warmup --factory

    **Fabrika** olarak yazıldı (modül seviyesinde `app = ...` DEĞİL): modülü
    içe aktarmanın yan etkisi olmamalı, yoksa her test içe aktarması bir
    ısıtma thread'i başlatır ve model indirmeye kalkar.
    """
    import threading
    book = os.environ.get("BOOK_PATH", "data/lise/12/biyoloji/kitap.pdf")
    sinif = os.environ.get("SINIF", "12")
    ders = os.environ.get("DERS", "biyoloji")
    for uyari in _yapilandirma_uyarilari():
        print(f"[http][UYARI] {uyari}", flush=True)

    service = _LazyService()

    def _isit():
        import time as _t
        t0 = _t.time()
        try:
            service.ata(build_service(book, sinif=sinif, ders=ders))
            print(f"[http] pipeline hazır ({_t.time() - t0:.1f}s)", flush=True)
        except Exception as e:                   # noqa: BLE001
            service.hata = f"{type(e).__name__}: {e}"
            print(f"[http][HATA] pipeline kurulamadı: {service.hata}", flush=True)

    print(f"[http] pipeline ARKA PLANDA kuruluyor: {book} ({sinif}/{ders})",
          flush=True)
    threading.Thread(target=_isit, name="warmup", daemon=True).start()
    return create_app(service)


def main() -> None:
    import uvicorn
    app = create_app_with_warmup()
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000"))
    print(f"[http] hazır → http://{host}:{port}  (/health, /ready, /rag/*)")
    # #50/OPS-13: graceful shutdown yoktu -- SIGTERM ucusta olan istekleri
    # kesiyordu. Artik acik sureli bekleme var.
    uvicorn.run(app, host=host, port=port,
                timeout_graceful_shutdown=int(GRACEFUL_SHUTDOWN_S))


if __name__ == "__main__":
    main()
