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
import sys
import warnings

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

# #96 saglayici secimi. MODUL SEVIYESINDE olmak ZORUNDA: `SharedModels` de
# bunlari kullaniyor ve `build_service` icine gomuldugunde calisma aninda
# `NameError: name 'build_embedder' is not defined` veriyordu -- yalnizca
# gercek servis kosuldugunda ortaya cikan, testlerin kacirdigi bir hata.
from ..embed.provider import build_embedder
from ..embed.provider import provider_warnings as _emb_warn
from ..rerank.provider import (build_reranker, check_abstain_compatibility,
                               provider_warnings as _rr_warn)

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


class ScopePairModel(BaseModel):
    """rag.chat kapsamı — bir (sınıf, ders) ÇİFTİ.

    YENİ biçim (backend `RagScopePair`): eski `role.sinif` + `role.ders_list`
    KARTEZYEN çarpım ifade ediyordu; çift listesi her grant'i tek tek taşır.
    `sinif` boş/None = sınıfa bağlı olmayan korpus (okul kulübü/etüt).
    """
    sinif: str | None = Field(default=None, max_length=16)
    ders: str = Field(min_length=1, max_length=64)


class ChatOptions(BaseModel):
    """Eskiden serbest `dict`ti ve `int(opts.get(...))` ile handler'a geciyordu."""
    top_n: int = Field(default=6, ge=1, le=20)
    candidate_n: int = Field(default=40, ge=1, le=200)
    ders: str | None = Field(default=None, max_length=64)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    history: list[dict] | None = Field(default=None, max_length=MAX_HISTORY_TURNS)
    role: RoleModel | None = None
    # rag.chat kapsamı: (sınıf,ders) ÇİFT listesi (eski `role.sinif`+`ders_list`
    # GERİYE UYUMLU çalışır). Kısa liste; çift başına sınır ders adıyla aynı.
    scope: list[ScopePairModel] | None = Field(default=None, max_length=200)
    options: ChatOptions = Field(default_factory=ChatOptions)
    # KİRACI (tenancy): isteğin okulu. Üretimde bu alanı backend doldurur
    # (hab/2 çerçevesinin `school`'u — bkz. bridge/), HTTP yüzeyi ise backend'in
    # ARKASINDA çalışır. OKULSUZ İSTEK REDDEDİLİR (`school_required`) ve okulsuz
    # okur HİÇBİR satır görmez: paylaşılan/"public" bir boyut YOKTUR
    # (fail-closed, bkz. guard/tenant.py + service/registry.resolve).
    school: str | None = Field(default=None, max_length=64)


class ScopeModel(BaseModel):
    pages: list[int] | None = Field(default=None, max_length=MAX_SCOPE_PAGES)
    span_ids: list[str] | None = Field(default=None, max_length=MAX_SPAN_IDS)
    ders: str | None = Field(default=None, max_length=64)
    sinif: str | None = Field(default=None, max_length=16)
    scope_label: str = Field(default="", max_length=200)


class SummarizeRequest(BaseModel):
    scope: ScopeModel
    role: RoleModel | None = None
    school: str | None = Field(default=None, max_length=64)   # kiracı (bkz. ChatRequest)


class QuestionsRequest(BaseModel):
    scope: ScopeModel
    role: RoleModel | None = None
    school: str | None = Field(default=None, max_length=64)   # kiracı (bkz. ChatRequest)
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
        except Exception as e:                                  # noqa: BLE001
            # SESSİZ 503 SINIFI (canlıda yakalandı, 2026-09-17): bu dal
            # yakalanmamış hatayı tipli cevaba çevirir ama İZ BIRAKMIYORDU —
            # iki `/rag/chat` isteği 503 döndü ve logda nedeni HİÇ görünmedi;
            # gerçek sebep (sağlayıcının geçici hatası) ancak elle tekrar
            # deneyip gözlemleyerek anlaşıldı. Artık tür + mesaj (kısaltılmış)
            # loglanır; SIR yazılmaz, istemciye de yalnız tipli gövde gider.
            print(f"[http][HATA] istek {rid}: {type(e).__name__}: {str(e)[:300]}",
                  file=sys.stderr, flush=True)
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
        # #75/OPS — SAĞLAYICI-mi, KORPUS-mi? Konteyner yeniden yaratıldığında
        # indeks bellekte olduğu için bir süre "hazır ama soru cevaplayamaz"
        # durumu vardı; operatör bunu `/ready`den AYIRT EDEMİYORDU. `korpus_hazir`
        # gerçekten KURULU bir indeks var mı der; `hazir_tur` ikisini ayırır:
        #   tam       → sağlayıcı hazır VE en az bir korpus kurulu (soru cevaplanır)
        #   saglayici → sağlayıcı hazır, korpus henüz YOK/İNŞA EDİLİYOR (cevap yok)
        #   yok       → sağlayıcı bile hazır değil
        korpus_hazir = (bool(getattr(service, "korpus_hazir"))
                        if hasattr(service, "korpus_hazir")
                        else getattr(service, "doc", None) is not None)
        hazir_tur = ("tam" if (hazir and korpus_hazir)
                     else "saglayici" if hazir else "yok")
        return JSONResponse(status_code=200 if hazir else 503,
                            content={"status": "ready" if hazir else "not_ready",
                                     "korpus_hazir": korpus_hazir,
                                     "hazir_tur": hazir_tur,
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
                                                  "cors": bool(origins)},
                                     # #96: operator "neden bu kadar yavas?"
                                     # sorusunu /ready'den cevaplayabilmeli.
                                     # CPU'ya sessiz dusus aksi halde yalniz
                                     # gecikmeden anlasilir.
                                     "cuda": cuda_status(),
                                     # #96 + API varsayilani: operator "hangi
                                     # saglayici kosuyor" sorusunu /ready'den
                                     # cevaplayabilmeli; eksik yapilandirma
                                     # acilista reddedildigi icin burada
                                     # YALNIZ ad gorunur (sir yazilmaz).
                                     "saglayici": _saglayici_raporu(),
                                     # #86: operator "hangi ders hazir"
                                     # sorusunu tahminle degil uctan
                                     # cevaplayabilmeli; ilk sorusu yavas
                                     # olacak dersler gorunur olmali.
                                     **({"korpus": service.status()}
                                        if hasattr(service, "status") else {})})

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

# M4-9 (#83, EXP-010/OPS-11) -- CACHE URETIMDE HIC BAGLI DEGILDI.
# Olculdu: `BGEM3Embedder()` -> cache=None; `Generator(...)` cagrisinda
# `response_cache` VERILMIYORDU. Yani her soru LLM'e gidiyordu ve
# OPTIMIZATION.md §C'deki maliyet kazanci (ResponseCache "DeepSeek cagrisini
# sifirlar") HIC GERCEKLESMIYORDU.
# Varsayilan KAPALI birakildi: cache acmak bir davranis degisikligidir ve
# #77'ye gore `corpus_version` olmadan TEHLIKELIDIR (silinmis kaynaga atif).
# `build_service` corpus_version'i zaten dolduruyor.
CACHE_PATH = os.environ.get("RAG_CACHE_PATH") or ""
CACHE_MAX_BYTES = int(os.environ.get("RAG_CACHE_MAX_BYTES", str(512 * 1024 * 1024)))
CACHE_TTL_S = float(os.environ.get("RAG_CACHE_TTL_S", "3600"))

# M4-13 (#87, EXP-010/OPS-14) — SOZLESME COK-TURLU REWRITE VAAT EDIYOR,
# KOD YOK SAYIYOR. `build_service` hic `rewriter` gecirmiyordu; yani
# `history` alani API-CONTRACT'ta duruyor ama uretimde SESSIZCE ATILIYORDU.
# Kullanici "peki devami?" diye soruyor, sistem onceki turu hic gormuyor.
# Maliyet: gecmisli her soruda BIR EK LLM cagrisi (~$0.0002). Kapatilabilir.
REWRITE_HISTORY = os.environ.get("RAG_REWRITE_HISTORY", "1") not in (
    "0", "", "false", "False")



# #96 (EXP-018) — GPU ZORUNLULUĞU.
#
# ÖLÇÜLDÜ (RTX 4060 Laptop, 10/biyoloji, gerçek `/rag/chat`):
#   CPU: 40 adaylık rerank 95,9 s · uçtan uca ~96 s  -> kapı O-05 GEÇİLMEZ
#   GPU: 40 adaylık rerank  1,9 s · p50 4,96 s       -> GEÇİLİR
#
# torch, CUDA bulamazsa SESSİZCE CPU'ya düşer. Konteynerde bu, sağlıklı
# görünen ama her soruya bir buçuk dakikada cevap veren bir servis demektir —
# demo sırasında "bozuk" diye okunur ve nedeni görünmez (log'da tek satır bile
# yok). `RAG_REQUIRE_CUDA=1` bu düşüşü AÇILIŞTA hataya çevirir.
#
# Varsayılan KAPALI: GPU'suz geliştirme ve CPU kurulumu bozulmasın.
REQUIRE_CUDA = os.environ.get("RAG_REQUIRE_CUDA", "").strip().lower() in (
    "1", "true", "yes", "on")


def cuda_status() -> dict:
    """CUDA görünürlüğü — `/ready` bunu makine-okunur raporlar.

    TORCH IMPORT ETMEDEN de cevap verir: varsayılan imge KÜÇÜKTÜR (API yolu,
    torch yok) ve o imajda import denemesi yalnız gürültü + gecikme üretir
    (torch importu bu makinede ~0,4 GB RSS ölçüldü). Kurulu olduğunda eskisi
    gibi raporlanır — davranış kaybı yok.
    """
    import importlib.util
    import sys as _sys
    # `find_spec` bir modül taklidi (test) ya da bozuk bir kurulum üzerinde
    # ValueError/ImportError atabilir; o zaman IMPORT yoluna bırakılır ve hata
    # eskisi gibi RAPORLANIR (torch'suz imajda ise hiç import denenmez).
    kurulu = "torch" in _sys.modules
    if not kurulu:
        try:
            kurulu = importlib.util.find_spec("torch") is not None
        except (ImportError, ValueError):
            kurulu = True
    if not kurulu:
        return {"available": False, "device_count": 0, "required": REQUIRE_CUDA,
                "reason": "torch kurulu değil: bu imaj KÜÇÜK (API sağlayıcı yolu) "
                          "derlendi. Yerel modeller için RAG_LOCAL_VENV/"
                          "RAG_LOCAL_MODELS_DIR + deploy/provision_local_stack.sh, "
                          "ya `--build-arg WITH_LOCAL_MODELS=1`."}
    try:
        import torch
    except Exception as e:                                   # noqa: BLE001
        return {"available": False, "reason": f"torch yok: {type(e).__name__}",
                "device_count": 0, "required": REQUIRE_CUDA}
    try:
        var = bool(torch.cuda.is_available())
        return {"available": var,
                "device_count": (torch.cuda.device_count() if var else 0),
                "device_name": (torch.cuda.get_device_name(0) if var else ""),
                "torch_cuda_build": torch.version.cuda,
                "required": REQUIRE_CUDA}
    except Exception as e:                                   # noqa: BLE001
        return {"available": False, "reason": f"{type(e).__name__}: {e}",
                "device_count": 0, "required": REQUIRE_CUDA}


def require_cuda_or_fail() -> None:
    """`RAG_REQUIRE_CUDA=1` iken GPU yoksa AÇILIŞTA hata.

    Sessizce CPU'ya düşmektense açıkça durmak yeğdir: 96 s'lik bir "çalışan"
    servis, çalışmayan bir servisten daha kötüdür — ilki demo sırasında
    fark edilir, ikincisi kurulumda.
    """
    if not REQUIRE_CUDA:
        return
    d = cuda_status()
    if not d.get("available"):
        raise RuntimeError(
            "RAG_REQUIRE_CUDA=1 ama CUDA GORUNMUYOR (" + str(d.get("reason") or
            f"torch cuda derlemesi={d.get('torch_cuda_build')}") + "). "
            "Kontrol listesi: (1) imge GPU torch ile kuruldu mu "
            "(--build-arg TORCH_INDEX=.../whl/cu130), (2) ana makinede "
            "nvidia-container-toolkit kurulu ve `nvidia-ctk cdi generate` "
            "calistirildi mi, (3) kaba `--device nvidia.com/gpu=all` verildi mi. "
            "CPU'ya dusmek 40 adaylik rerank icin ~96 s demektir (kapi O-05: 6 s).")


class SharedModels:
    """Korpuslar arasında PAYLAŞILAN ağır bileşenler (#86 çok-korpus).

    ÖLÇÜLEN SORUN: `build_service` her çağrıda kendi embedder ve reranker'ını
    kuruyordu. Tek kitapta sorun değil; 15 kitaplık bir okul kurulumunda 15 ×
    (BGE-M3 2,3 GB + reranker 2,3 GB) demek — 8 GB GPU'da OOM.

    Modeller korpustan BAĞIMSIZDIR (aynı ağırlıklar, farklı metin). İndeksler
    ise korpusa özeldir ve paylaşılamaz.
    """

    def __init__(self):
        import threading
        # RLock ZORUNLU: `reranker` ozelligi kilidi tutarken uyari uretmek icin
        # `self.embedder`'a bakiyor, o da AYNI kilidi istiyor. Duz `Lock` ile
        # bu bir DEADLOCK'tur ve KOSARAK BULUNDU: korpus kurulum thread'i
        # sessizce sonsuza kadar bekliyor, `/ready` hep "kuruluyor" diyor,
        # hicbir hata log'u dusmuyordu. Belirti "cok yavas"; sebep "hic
        # ilerlemiyor".
        self._lock = threading.RLock()
        self._embedder = None
        self._reranker = None
        self._response_cache = None

    @property
    def embedder(self):
        with self._lock:
            if self._embedder is None:
                self._embedder = build_embedder()
            return self._embedder

    @property
    def reranker(self):
        with self._lock:
            if self._reranker is None:
                r = build_reranker()
                from ..generate.generator import ABSTAIN_SCORE_DEFAULT
                check_abstain_compatibility(
                    r, abstain_score=ABSTAIN_SCORE_DEFAULT)
                # Kilit altinda ozellik cagirmak yerine mevcut ornege bak:
                # gomme henuz kurulmadiysa onun uyarisi zaten `build_service`
                # akisinda uretilir.
                _emb = self._embedder
                for _u in ((_emb_warn(_emb) if _emb is not None else [])
                           + _rr_warn(r)):
                    warnings.warn(_u, RuntimeWarning, stacklevel=2)
                    print(f"[http][UYARI] {_u}", flush=True)
                r.warmup()
                self._reranker = r
            return self._reranker

    @property
    def response_cache(self):
        """Cache TEK backend'te paylaşılır; anahtar zaten `ders` ve
        `corpus_version` taşıdığı için korpuslar birbirinin cevabını görmez
        (bkz. cache/response_cache.py + test_cache_invalidation)."""
        with self._lock:
            if self._response_cache is None and CACHE_PATH:
                from ..cache.base import SQLiteCache
                from ..cache.response_cache import ResponseCache
                backend = SQLiteCache(CACHE_PATH, max_bytes=CACHE_MAX_BYTES)
                backend.evict_lru()
                self._response_cache = ResponseCache(backend, ttl=CACHE_TTL_S)
            return self._response_cache


def build_service(book_path: str, *, school, sinif: str, ders: str,
                  corpus_version: str = "",
                  ocr: bool = False, vlm: bool = False,
                  include_parents: bool | None = None,
                  shared: "SharedModels | None" = None):
    """Gerçek pipeline'ı kurup RagService döndürür (ağır: PDF parse + BGE modelleri +
    indeks). main()/üretim için. corpus_version cache anahtarına girer (#30).

    `school` ZORUNLUDUR ve varsayılanı yoktur: korpusun SAHİBİdir (okul slug'ı;
    paylaşılan/"public" bir boyut YOKTUR). Sahipsiz kurulan bir korpus, bir
    okulun kitabını herkese açabilirdi (bkz. guard/tenant.py).

    `include_parents`: parent chunk'lar `chunks_by_id`'ye girsin mi (yani
    `rerank_select` parent genisletmesi ETKIN olsun mu). None -> env varsayilani."""
    from ..guard.tenant import require_owner
    sahip = require_owner(school)
    require_cuda_or_fail()        # #96: sessizce CPU'ya dusme
    if include_parents is None:
        include_parents = INCLUDE_PARENTS_DEFAULT
    from ..ingest.canonical import build_canonical
    from ..chunk import chunk_document
    from ..index import DenseIndex, BM25Index
    from ..retrieve import SparseIndex, HybridRetriever
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
    # #96: gomme saglayicisi env ile secilir (local | api | cohere). Varsayilan
    # local -- olculmus butun kalite sayilari (EXP-011/013/017/018) o yola aittir.
    # `cohere` yolunda ilk gomme indeksin boyutunu (1024) dogrular; farkli
    # boyutlu model ADIYLA reddedilir (bkz. embed/provider.py::INDEX_DIM).
    emb = shared.embedder if shared is not None else build_embedder()
    # #82 (EXP-010/OPS-10): dense ve sparse TEK geçişte üretilir. Ayrı
    # çağrıldığında korpus iki kez kodlanıyordu. Gerçek kitapla ölçüldü
    # (10-biyoloji, 327 chunk, GPU): iki geçiş 8,4 s -> tek geçiş 3,9 s (%53).
    #
    # #75 — İNDEKS ÖNBELLEĞİ. Gömme AĞ çağrısıdır (yerel yolda CPU'da dakikalar);
    # çıktısı içerik+model türevlidir, bu yüzden volume'de saklanır ve yeniden
    # yaratılan konteynerde AYNI korpus için tekrar ödenmez. Kalıcılık sözleşmesi
    # ve anahtar türetimi: src/index/disk_cache.py başlığı.
    from ..embed import provider as _embed_provider
    from ..index import disk_cache as _disk
    _root = _disk.cache_root()
    _sig = _disk.embed_signature(_embed_provider.PROVIDER,
                                 _embed_provider.API_BASE,
                                 _embed_provider.API_MODEL,
                                 _embed_provider.INDEX_DIM)
    _key = _disk.cache_key(doc.doc_id, texts, _sig)
    _hit = _disk.load(_root, doc.doc_id, _key, dim=_embed_provider.INDEX_DIM,
                      n=len(ids)) if _root else None
    if _hit is not None and _hit[0] == ids:
        _, vecs, sparse = _hit
        print(f"[indeks] onbellek isabeti: {doc.doc_id} "
              f"({len(ids)} chunk) — gömme ATLANDI", flush=True)
    else:
        vecs, sparse = emb.embed_both(texts, batch_size=16)
        if _root:
            _yazildi = _disk.save(_root, doc.doc_id, _key, ids, vecs, sparse)
            if _yazildi:
                print(f"[indeks] onbellege yazildi: {doc.doc_id} "
                      f"({len(ids)} chunk)", flush=True)
    meta = {c.chunk_id: {"sinif": sinif, "ders": ders, "school": sahip}
            for c in children}
    retr = HybridRetriever(emb, DenseIndex(dim=1024).build(ids, vecs, school=sahip),
                           BM25Index().build(ids, texts, school=sahip),
                           SparseIndex().build(ids, sparse, school=sahip),
                           meta=meta)
    # #83: cache YALNIZ acik yol ve corpus_version varsa kurulur.
    if shared is not None:
        response_cache = shared.response_cache
    else:
        response_cache = None
        if CACHE_PATH:
            from ..cache.base import SQLiteCache
            from ..cache.response_cache import ResponseCache
            backend = SQLiteCache(CACHE_PATH, max_bytes=CACHE_MAX_BYTES)
            backend.evict_lru()           # acilista tavanin altina in
            response_cache = ResponseCache(backend, ttl=CACHE_TTL_S)

    span_meta = build_span_meta(doc)
    # #80/#82 — RERANKER'I DA ISIT. KONTEYNERDE KOSULARAK BULUNDU:
    # `build_service` embedder'i chunk'lari gomerek dolayli olarak yukluyor ama
    # reranker TEMBEL kaliyordu. `/ready` "hazir" diyor, ilk gercek soru gelince
    # reranker ~2 GB indirmeye kalkiyor ve istek son tarihini (60 s) asip
    # `reason="timeout"` donuyordu. Yani hazirlik sinyali YALAN soyluyordu.
    if shared is not None:
        reranker = shared.reranker           # uyarilar + kapi kontrolu orada
    else:
        reranker = build_reranker()
        # Kanit kapisi bu saglayiciyla anlamli mi? Degilse ACILISTA hata:
        # sessizce devre disi kalmis bir fail-closed kapi, hic olmayandan daha
        # tehlikelidir (operator korumali sandigi icin).
        from ..generate.generator import ABSTAIN_SCORE_DEFAULT
        check_abstain_compatibility(reranker, abstain_score=ABSTAIN_SCORE_DEFAULT)
        for _u in (_emb_warn(emb) + _rr_warn(reranker)):
            warnings.warn(_u, RuntimeWarning, stacklevel=2)
            print(f"[http][UYARI] {_u}", flush=True)
        reranker.warmup()
    # #87/OPS-14: cok-turlu rewrite BAGLANDI (sozlesme zaten vaat ediyordu).
    rewriter = None
    if REWRITE_HISTORY:
        from ..memory.history_rewrite import HistoryAwareRewriter
        rewriter = HistoryAwareRewriter()
    gen = Generator(retr, reranker, by_id, span_meta, ders=ders,
                    safety_classifier=LLMSafetyClassifier(), context_packing=True,
                    corpus_version=cv, require_role=True,   # STRICT: rolsüz istek fail-closed
                    response_cache=response_cache, rewriter=rewriter)
    return RagService(gen, doc=doc, summarizer=Summarizer(),
                      question_gen=QuestionGenerator(), ders=ders, school=sahip)


def _saglayici_raporu() -> dict:
    """`/ready` için sağlayıcı seçimi — SIR YAZILMAZ, yalnız ad.

    Operatör "hangi sağlayıcı koşuyor" sorusunu log okumadan cevaplayabilsin
    (eksik yapılandırma zaten açılışta reddedilir → burada YALNIZCA seçim).
    """
    from ..embed import provider as _emb
    from ..rerank import provider as _rr
    gomme = (getattr(_emb, "PROVIDER", "") or "local").strip().lower()
    rr = (getattr(_rr, "PROVIDER", "") or "local").strip().lower()
    out = {"gomme": gomme, "rerank": rr}
    if "local" in (gomme, rr):
        # Yerel yığın artık imajda DEĞİL: volume'daki sağlamanın durumu
        # makine-okunur bildirilir ("sağlanmış için <tag>", "yok").
        from .preflight import yerel_yigin_durumu
        out["yerel_yigin"] = yerel_yigin_durumu()
    return out


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
    d = cuda_status()
    if not d.get("available") and not REQUIRE_CUDA:
        # Uyarı, hata değil: CPU kurulumu meşrudur ama gecikmesi ölçüldü.
        u.append("CUDA yok → CPU'da çalışılıyor; 40 adaylık rerank ~96 s "
                 "(kapı O-05: p50 ≤ 6 s). Interaktif kullanım için GPU gerekir "
                 "(#96/EXP-018).")
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

    @property
    def korpus_hazir(self) -> bool:
        """Korpus GERÇEKTEN kuruldu mu (`/ready`nin `hazir_tur`u için, #75)."""
        return self._gercek is not None and self.doc is not None

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


def _c_parse(spec):
    """Isıtma hedefi: `okul/sinif/ders` (iki parçalıysa bu örnek zaten okula
    sabitlenmiştir — bkz. MultiCorpusService `school=`)."""
    from .multi import _parcalar
    return _parcalar(spec)


def _kopruyu_baslat(service) -> None:
    """hab/2 köprüsünü arka planda başlat (dial-out).

    Sunucu ÖNCE ayağa kalksın diye BEKLENMEZ: köprü kendi thread'inde bağlanır
    ve backend yoksa üstel geri çekilmeyle sonsuza dek dener — HTTP yüzeyi
    (`/health`, `/ready`, `/rag/*`) bundan ETKİLENMEZ (aynı desen: ısıtma
    thread'i). Ayrıntı ve boot politikası: `src/bridge/transport.py` başlığı,
    `docs/BACKEND-INTEGRATION.md` §4.2.

    Köprü AYARLARI bozuksa (örneğin `AI_BRIDGE_PORT=abc`) HTTP yüzeyi yine de
    AÇILIR: sağlık uçları ayakta kalmalı ki operatör sorunu görebilsin.
    """
    from ..bridge.transport import start_in_background
    try:
        start_in_background(service)
    except Exception as exc:                       # noqa: BLE001
        print(f"[kopru][HATA] köprü başlatılamadı: {exc}", flush=True)


def create_app_with_warmup():
    """uvicorn giriş noktası — sunucu HEMEN ayağa kalkar, boru hattı arka planda.

    Koşum:
        uvicorn src.service.http_app:create_app_with_warmup --factory

    **Fabrika** olarak yazıldı (modül seviyesinde `app = ...` DEĞİL): modülü
    içe aktarmanın yan etkisi olmamalı, yoksa her test içe aktarması bir
    ısıtma thread'i başlatır ve model indirmeye kalkar.
    """
    import threading
    # TEMIZ KESIM (filo ad sozlesmesi): kaldirilmis saglayici anahtar adlari
    # (DEEPSEEK_API_KEY / NVIDIA_API_KEY) ortamda duruyorsa servis AYAGA
    # KALKMAZ. Sessizce yeni ada dusmek, adi degismemis bir operatoru kendi
    # ayar dosyasinin artik okunmadigini fark ettirmez. (LLM istemcisi de ayni
    # kapidan gecer; buradaki cagri onu konteyner acilisinda GORUNUR kilar.)
    from ..providers.llm import reject_retired_env
    reject_retired_env()
    # SAGLAYICI ON DENETIMI (fail-closed): `api` secilen saglayicinin taban
    # adresi/modeli/anahtari eksikse uvicorn DAHA PORTU DINLEMEDEN durur.
    # Eksik anahtarla ayaga kalkan servis /health ve /ready'de YESIL kalir,
    # yalniz ilk gercek soru duser -- "calisiyor gibi gorunen, hicbir istege
    # cevap veremeyen servis" (bkz. src/service/preflight.py).
    from .preflight import enforce as _preflight
    _preflight()
    # Okul segmenti ZORUNLU (kiracılık): `<kök>/<okul>/<kasa>/<sınıf>/<ders>/kitap.pdf`
    # — düzeni taşımayan yol açık hata verir (multi.school_from_book_path).
    book = os.environ.get("BOOK_PATH", "data/okul-a/lise/12/biyoloji/kitap.pdf")
    sinif = os.environ.get("SINIF", "12")
    ders = os.environ.get("DERS", "biyoloji")
    for uyari in _yapilandirma_uyarilari():
        print(f"[http][UYARI] {uyari}", flush=True)

    # #86 — COK-KORPUS. `RAG_CORPORA` verilirse servis birden cok derse
    # cevap verir. Verilmezse davranis ESKISIYLE AYNI (tek BOOK_PATH) --
    # mevcut kurulumlar bozulmasin.
    #
    # ÜRÜN AÇISINDAN NEDEN ÖNEMLİ: diskte 15 kitap var (lise 10) ve tek-korpus
    # modda ürün yalnız birine cevap veriyor. Okul demosunda öğrenci kimyaya
    # geçtiği anda "kaynaklarda bulunamadı" alır; bu RAG hatası gibi görünür
    # ama o korpus hiç yüklü değildir.
    from .multi import CORPORA, WARM_ON_START, MultiCorpusService, spec_label
    if CORPORA:
        # `RAG_CORPORA` OKUL ADI TAŞIMAZ: girdileri yalnız DERS SÜZGECİdir
        # ("all" = süzgeç yok). Okullar —ve korpusları— DİSKTEN keşfedilir
        # (`data/<okul>/<kasa>/<sınıf>/<ders>/kitap.pdf`); "hangi okullar var"
        # sorusu bir env değişkeniyle cevaplanmaz (bkz. guard/tenant.py).
        specs = [] if CORPORA == ["all"] else list(CORPORA)
        multi = MultiCorpusService(specs, discover_tenants_=True)
        print(f"[http] cok-korpus: {len(multi.known())} korpus "
              f"({', '.join(spec_label(k) for k in multi.known()[:6])}"
              f"{' ...' if len(multi.known()) > 6 else ''})", flush=True)
        # Korpuslar TEMBEL kurulur; istenirse acilista isitilir. Hepsini
        # acilista kurmak ~12 dk sagir servis demekti (tek kitap GPU'da 47,6 s)
        # ve indeks kalici olmadigi icin (#75) bu bedel HER restart'ta odenir.
        if WARM_ON_START:
            hedef = (multi.known() if WARM_ON_START.lower() == "all"
                     else [_c_parse(x) for x in WARM_ON_START.split(",") if x.strip()])

            def _isit_cok():
                import time as _t
                t0 = _t.time()
                sonuc = multi.warm(hedef)
                print(f"[http] isitma bitti ({_t.time() - t0:.1f}s): {sonuc}",
                      flush=True)

            threading.Thread(target=_isit_cok, name="warmup-multi",
                             daemon=True).start()
        _kopruyu_baslat(multi)
        return create_app(multi)

    service = _LazyService()

    def _isit():
        import time as _t
        t0 = _t.time()
        try:
            # BOOK_PATH tek-korpus modu: korpusun SAHİBİ (okul) yoldan okunur —
            # `<...>/<okul>/<kasa>/<sınıf>/<ders>/kitap.pdf`. Sahipsiz korpus
            # diye bir şey olmadığı için düzen bozuksa açıkça hata verilir
            # (bkz. multi.school_from_book_path).
            from .multi import school_from_book_path
            service.ata(build_service(book, school=school_from_book_path(book),
                                      sinif=sinif, ders=ders))
            print(f"[http] pipeline hazır ({_t.time() - t0:.1f}s)", flush=True)
        except Exception as e:                   # noqa: BLE001
            service.hata = f"{type(e).__name__}: {e}"
            print(f"[http][HATA] pipeline kurulamadı: {service.hata}", flush=True)

    print(f"[http] pipeline ARKA PLANDA kuruluyor: {book} ({sinif}/{ders})",
          flush=True)
    threading.Thread(target=_isit, name="warmup", daemon=True).start()
    _kopruyu_baslat(service)
    return create_app(service)


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `--validate` (kardes servislerdeki desen): yalniz yapilandirmayi denetler,
    # sunucuyu ACMAZ. Gercek kapi `create_app_with_warmup` icindedir; bu bayrak
    # operatorun deploy oncesi ayni denetimi elle kosmasini saglar.
    if "--validate" in argv:
        from .preflight import main as _preflight_main
        raise SystemExit(_preflight_main([a for a in argv if a != "--validate"]))
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
