"""Backend'in tel biçimi (hab/2 köprüsü + REST DTO'ları) — Python karşılığı.

KAYNAK (bu depoda DEĞİŞTİRİLMEZ, yalnız okunur):
  hezarfen_backend/src/ai/protocol.rs   — hab/2 çerçeveleri
  hezarfen_backend/src/ai/chat.rs       — `chat.reply` yeteneği
  hezarfen_backend/src/ai/rag.rs        — `rag.index` yeteneği
  hezarfen_backend/src/web/*.rs         — REST uçları ve DTO'ları

Backend'in kendi testi (`rag_payload_keys_are_the_documented_wire_names`) şunu
söylüyor: *"Services in other languages match on these literals — a rename here
silently breaks every one of them, so pin the encoding."* Biz o "başka dildeki
servis"iz; bu yüzden burada da aynı sabitleme testle yapılır
(`tests/unit/test_backend_sozlesme.py`).

MİMARİ NOT — KÖPRÜ YÖNÜ TERS:
Backend QUIC **sunucusudur**, AI servisleri ona **dial eder**. Yani bizim
FastAPI servisimizi backend ÇAĞIRMAZ; biz bağlanır, `Hello` ile yeteneklerimizi
duyurur ve backend'in açtığı akışlarda `Request` çerçevesi bekleriz. Mevcut
`src/service/http_app.py` bu köprünün yerine geçmez — onun yanında durur
(yerel geliştirme + backend dışı entegrasyonlar için).
"""
from __future__ import annotations

import asyncio
import json
import struct
from dataclasses import dataclass, field, asdict

# --- yetenek adları (constant.rs) ---
AI_CHAT_CAPABILITY = "chat.reply"
AI_RAG_INDEX_CAPABILITY = "rag.index"
AI_RAG_CHAT_CAPABILITY = "rag.chat"      # RAG'e özel kutu (chatbot'tan AYRI)
AI_PROTOCOL = "hab/2"

# --- taşıma sabitleri (el sıkışma + çerçeveleme) ---------------------------
# Kaynak: `hezarfen_backend/src/constant.rs`. Değerler ZEKA'nın kanıtlanmış
# istemcisiyle (`hezarfen_zeka/service/src/protocol.py`) BİREBİR aynıdır: aynı
# backend, aynı tel. Burada olmalarının sebebi: tel biçiminin TEK evi burası
# (`protocol.rs` + `constant.rs` karşılığı), taşıma ise yalnız bunları kullanır.
AI_ALPN = "hab/2"
"""`constant.rs:531` — TLS ALPN. Sürüm kapısı BURADA da reddeder: `hab/1`
konuşan bir servis el sıkışmada elenir, kaydolamaz."""

AI_MAX_FRAME_BYTES = 8 * 1024 * 1024
"""`constant.rs:536` — tek çerçevenin tavanı. Uzunluk ÖNEKİ, gövde ayrılmadan
ÖNCE denetlenir; kötü bir uzunluk bellek tüketemez (`protocol.rs:286-289`)."""

AI_MAX_CONCURRENT_PER_WORKER = 64
"""`constant.rs:547` — backend `Hello.max_concurrent`i 1..=64 arasına kırpar."""

AI_IDLE_TIMEOUT_SECS = 30
"""`constant.rs:554` — QUIC boşta kalma zaman aşımı."""

AI_KEEPALIVE_SECS = 10
"""`constant.rs:555` — PING aralığı: boşta kalma penceresinin çok altında ki
sağlıklı ama sessiz bir servis düşürülmesin. Uygulama düzeyinde heartbeat
ÇERÇEVESİ yoktur (`protocol.rs:13-14`)."""

CERTIFICATE_PATH = "/ai/certificate"
"""`src/web/ai.rs` — `certificate_pem` + `fingerprint_sha256` döner."""

GREETING_TIMEOUT_SECS = 8.0
"""Bizim değerimiz: backend'in el sıkışma penceresinin (10 s) ALTINDA tutulur ki
reddi biz görelim, akış altımızdan kesilmesin."""

PERMANENT_REJECTS = ("unauthorized", "unsupported_protocol")
"""Yapılandırma/dağıtım değişmeden düzelmeyen retler (`server.rs:1030-1046`).
Bekleme yine sürer — çıkmak yok — ama tavana çekilir: kalıcı bir redde gürültü
yapmadan bekleriz ve sorun düzeldiğinde kendiliğinden bağlanırız."""

# Backend'in kabul ettiği okul rolleri (domain/role.rs — `ai` ATANAMAZ).
ASSIGNABLE_ROLES = ("parent", "student", "teacher", "manager", "admin")


# --------------------------------------------------------------- chat.reply

@dataclass
class ChatTurn:
    """Bir önceki mesaj. `role` KİMİN SÖYLEDİĞİ ("user"/"assistant")."""
    role: str
    content: str

    def to_wire(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatRequestPayload:
    """Backend'in `chat.reply` için gönderdiği gövde.

    DİKKAT — burada ÖĞRENCİ KİMLİĞİ YOK. Backend yalnız `asker_role` gönderiyor
    ("the backend only forwards the role"). Yani servis hangi öğrencinin
    sorduğunu BİLEMEZ; o öğrencinin notlarını çekemez, sınıf/ders kasası
    izolasyonunu uygulayamaz. Kişiselleştirme bu sözleşmeyle MÜMKÜN DEĞİL.
    Ayrıntı ve öneri: `docs/BACKEND-ENTEGRASYON.md`.
    """
    message: str
    asker_role: str
    history: list[ChatTurn] = field(default_factory=list)

    @classmethod
    def from_wire(cls, d: dict) -> "ChatRequestPayload":
        return cls(message=d["message"], asker_role=d["asker_role"],
                   history=[ChatTurn(t["role"], t["content"])
                            for t in d.get("history", [])])

    def to_wire(self) -> dict:
        return {"message": self.message, "asker_role": self.asker_role,
                "history": [t.to_wire() for t in self.history]}


@dataclass
class ChatReplyPayload:
    """Servisin döndürdüğü gövde — **yalnız metin**.

    DİKKAT: `citations`/`abstained`/`reason` için köprüde yer YOK. Bizim ürün
    sözümüz ("her cümle kaynağa dayanır, atıfa tıklayınca sayfayı bulursun")
    bu sözleşmeyle kullanıcıya ULAŞAMAZ. Geçici çözüm, atıfları metnin içine
    okunabilir biçimde gömmektir; kalıcı çözüm sözleşme değişikliğidir.
    """
    text: str

    def to_wire(self) -> dict:
        return {"text": self.text}


# ---------------------------------------------------------------- rag.index

@dataclass
class RagFile:
    """Notun bir eki — **yalnız meta**. Baytlar `BlobRequest` ile ayrı gelir."""
    id: str
    name: str
    content_type: str
    size: int

    def to_wire(self) -> dict:
        return asdict(self)


@dataclass
class RagIndexPayload:
    """Backend'in indekslenmesini istediği ders notu.

    `author`: dosya baytları bu kullanıcı ADINA okunur (`on_behalf_of`) —
    notun öğretmeni kendi dersini her zaman görebilir, `ai` görevlisi ise
    HİÇBİR ZAMAN göremez.
    """
    course_note: str
    course: str
    author: str
    title: str
    content: str
    files: list[RagFile] = field(default_factory=list)

    @classmethod
    def from_wire(cls, d: dict) -> "RagIndexPayload":
        return cls(course_note=d["course_note"], course=d["course"],
                   author=d["author"], title=d["title"], content=d["content"],
                   files=[RagFile(**f) for f in d.get("files", [])])

    def to_wire(self) -> dict:
        return {"course_note": self.course_note, "course": self.course,
                "author": self.author, "title": self.title,
                "content": self.content,
                "files": [f.to_wire() for f in self.files]}


@dataclass
class RagIndexReplyFile:
    """İndekslenen TEK ekin backend'e geri bildirimi — `id` → `doc_id` eşleşmesi.

    `id`: isteğin `RagFile.id`'si — **AYNI değer**. `doc_id`: o ekin indekste
    kazandığı korpus kimliği (`<dosya sha256 ilk 12>`; bkz. ingest/canonical.py).
    Backend bu eşleşmeyle `course_note_file.rag_doc_id`'yi doldurur; sonra bir
    eki yeniden indekslerken/silerken hangi korpusu hedefleyeceğini bilir.
    """
    id: str
    doc_id: str

    @classmethod
    def from_wire(cls, d: dict) -> "RagIndexReplyFile":
        return cls(id=d["id"], doc_id=d["doc_id"])

    def to_wire(self) -> dict:
        return {"id": self.id, "doc_id": self.doc_id}


@dataclass
class RagIndexReply:
    """Servisin `rag.index`'e döndürdüğü gövde — her ek için `id`→`doc_id`.

    Backend bunu OKUR (isteği bir yanıt bekler): hangi gönderdiği `course_note_file`
    id'sinin hangi korpus `doc_id`'sine karşılık geldiğini yalnız bu yanıttan öğrenir.
    """
    files: list[RagIndexReplyFile] = field(default_factory=list)

    @classmethod
    def from_wire(cls, d: dict) -> "RagIndexReply":
        return cls(files=[RagIndexReplyFile.from_wire(f)
                          for f in d.get("files", [])])

    def to_wire(self) -> dict:
        return {"files": [f.to_wire() for f in self.files]}


# ---------------------------------------------------------------- rag.chat
# Backend'in RAG'e ÖZEL yeteneği (chatbot'un `chat.reply`'inden AYRI; otorite:
# hezarfen_backend README `## AI bridge (QUIC)` → `### The rag.chat capability`).
# `asker_role` AYRI bir alandır: servis rolü buradan okur (bkz. API-CONTRACT
# §0.2(a) — eskiden `asker_role` → `role` eşlemesi YOKTU; artık `bridge/
# dispatch.py` yapar).

@dataclass
class RagChatRequestPayload:
    message: str
    asker: str
    asker_role: str
    scope: list["RagScopePair"] = field(default_factory=list)
    history: list[ChatTurn] = field(default_factory=list)

    @classmethod
    def from_wire(cls, d: dict) -> "RagChatRequestPayload":
        return cls(message=d["message"], asker=str(d.get("asker") or ""),
                   asker_role=str(d.get("asker_role") or ""),
                   scope=[RagScopePair.from_wire(p) for p in d.get("scope", [])],
                   history=[ChatTurn(**t) for t in d.get("history", [])])

    def to_wire(self) -> dict:
        return {"message": self.message, "asker": self.asker,
                "asker_role": self.asker_role,
                "scope": [p.to_wire() for p in self.scope],
                "history": [t.to_wire() for t in self.history]}


@dataclass
class RagCitation:
    """`rag.chat` yanıtındaki tıklanabilir kaynak (backend `RagCitation`)."""
    n: int
    doc_id: str
    pages: list = field(default_factory=list)
    span_ids: list = field(default_factory=list)
    ders: str | None = None

    @classmethod
    def from_wire(cls, d: dict) -> "RagCitation":
        return cls(n=int(d.get("n") or 0), doc_id=str(d.get("doc_id") or ""),
                   pages=list(d.get("pages") or []),
                   span_ids=list(d.get("span_ids") or []),
                   ders=d.get("ders"))

    def to_wire(self) -> dict:
        return {"n": self.n, "doc_id": self.doc_id, "pages": list(self.pages),
                "span_ids": list(self.span_ids), "ders": self.ders}


@dataclass
class RagChatReplyPayload:
    text: str
    abstained: bool = False
    reason: str = ""
    citations: list[RagCitation] = field(default_factory=list)

    @classmethod
    def from_wire(cls, d: dict) -> "RagChatReplyPayload":
        return cls(text=str(d.get("text") or ""),
                   abstained=bool(d.get("abstained", False)),
                   reason=str(d.get("reason") or ""),
                   citations=[RagCitation.from_wire(c)
                              for c in d.get("citations", [])])

    def to_wire(self) -> dict:
        return {"text": self.text, "abstained": self.abstained,
                "reason": self.reason,
                "citations": [c.to_wire() for c in self.citations]}


# ----------------------------------------------------- scope (sınıf/ders ÇİFTİ)

@dataclass
class RagScopePair:
    """`rag.chat` kapsamı: bir (sınıf, ders) ÇİFTİ.

    NEDEN ÇİFT (çapraz-çarpım güvenliği): eski biçim `role.sinif` + `role.ders_list`
    idi ve bu iki alan bir KARTEZYEN ÇARPIMI ifade eder — `sinif="10"` +
    `ders_list=["biyoloji","satranc"]` "10-biyoloji **VE** 10-satranç" demektir.
    Oysa gerçek kapsam "10-biyoloji **VEYA** okul-satranç" olabilir; düzleştirme
    (flatten) yanlış bir (sınıf,ders) grant'i AÇAR. Çift listesi her grant'i tek
    tek taşır, böylece hiçbir çift yanlışlıkla açılmaz.

    `sinif=None` = sınıfa bağlı OLMAYAN korpus (okul kulübü / etüt).
    """
    sinif: str | None
    ders: str

    @classmethod
    def from_wire(cls, d: dict) -> "RagScopePair":
        s = d.get("sinif")
        return cls(sinif=(str(s) if s not in (None, "") else None), ders=d["ders"])

    def to_wire(self) -> dict:
        return {"sinif": self.sinif, "ders": self.ders}


# ------------------------------------------------- servis -> backend okuma

@dataclass
class ApiRequest:
    """Servisin backend'den veri OKUMA çerçevesi.

    "That mirrors the REST API — the backend dispatches the path internally —
    so a service asks for school data instead of being handed it."

    `on_behalf_of` verilirse istek O KULLANICI olarak koşar (kendi yetkisiyle);
    verilmezse servisin kendi (`ai`) kimliğiyle koşar ve `ai` çoğu şeyi göremez.
    Öğrenci verisini çekmenin TEK yolu budur.
    """
    id: str
    school: str
    path: str
    query: str | None = None
    on_behalf_of: str | None = None
    method: str | None = None          # None -> GET

    def to_wire(self) -> dict:
        d = {"id": self.id, "school": self.school, "path": self.path}
        for ad, deger in (("query", self.query), ("on_behalf_of", self.on_behalf_of),
                          ("method", self.method)):
            if deger is not None:
                d[ad] = deger
        return d


@dataclass
class BlobRequest:
    """Ek dosyanın baytlarını okuma çerçevesi (JSON'a sığmaz, ham akar)."""
    id: str
    school: str
    file: str
    on_behalf_of: str | None = None

    def to_wire(self) -> dict:
        d = {"id": self.id, "school": self.school, "file": self.file}
        if self.on_behalf_of is not None:
            d["on_behalf_of"] = self.on_behalf_of
        return d


class BlobReadRefused(Exception):
    """A blob read that did not deliver bytes.

    The backend's own refusal vocabulary (`protocol.rs::BlobResponse::Err`:
    `not_found` for a file it does not have, `forbidden` for one the named
    reader may not open, `module_disabled`, `unavailable`) plus the codes this
    side raises before/after the wire (`too_large`, `blob_unavailable`,
    `bad_header`, `unsupported_type`, `parse_failed`). Typed, never a bare
    `Exception`: one refused attachment must not abort a whole index.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class ApiError(Exception):
    """Köprü düzeyinde red (yol izinli değil, kullanıcı bilinmiyor).

    Koşup 404 dönen bir API çağrısı hata DEĞİLDİR — o `outcome:"ok"` içinde
    kendi durum koduyla gelir (backend'in kendi ifadesi).
    """


# ------------------------------------------- backend -> servis (hab/2 Request)

class BridgeFrameError(Exception):
    """Çerçeve okunamıyor (protocol.rs `FrameError::Malformed`)."""

    def __init__(self, message: str, code: str = "malformed"):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class BridgeRequest:
    """Backend'in AÇTIĞI akışta okunan tek çalışma birimi (`protocol.rs::Request`).

    Okul İKİ YÖNDE de taşınır: burada ZORUNLUDUR ve cevap onu AYNEN yazar.
    Backend'in kendi kuralı: *"Every request frame names its school by slug,
    and every answer echoes it … A frame without a `school` is `malformed` …
    there is no default and no fallback."* Bu yüzden `from_wire` okulsuz
    çerçeveyi reddeder — varsayılan bir okul YOKTUR (bkz. guard/tenant.py).
    """
    id: str
    school: str
    capability: str
    deadline_ms: int = 0
    payload: dict = field(default_factory=dict)

    @classmethod
    def from_wire(cls, d: dict) -> "BridgeRequest":
        if not isinstance(d, dict):
            raise BridgeFrameError("çerçeve bir JSON nesnesi değil")
        okul = d.get("school")
        if okul is None or not str(okul).strip():
            raise BridgeFrameError("`school` ZORUNLU (varsayılan/fallback yok)")
        for ad in ("id", "capability"):
            if not str(d.get(ad) or "").strip():
                raise BridgeFrameError(f"`{ad}` zorunlu")
        govde = d.get("payload")
        return cls(id=str(d["id"]), school=str(okul),
                   capability=str(d["capability"]),
                   deadline_ms=int(d.get("deadline_ms") or 0),
                   payload=govde if isinstance(govde, dict) else {})

    def to_wire(self) -> dict:
        return {"id": self.id, "school": self.school,
                "capability": self.capability, "deadline_ms": self.deadline_ms,
                "payload": self.payload}


@dataclass
class BridgeResponse:
    """Servisin tek cevabı (`protocol.rs::Response`). `school` İSTEĞİN AYNISI.

    `status` "ok" ya da "err"; `err` bir *işlenmiş* hatadır (kötü girdi, model
    reddi). Servis isteğin ortasında ölürse akış düşer — o taşıma hatasıdır,
    buraya girmez."""
    id: str
    school: str
    status: str = "ok"
    payload: dict | None = None
    code: str = ""
    message: str = ""

    @classmethod
    def ok(cls, req: "BridgeRequest", payload: dict) -> "BridgeResponse":
        return cls(id=req.id, school=req.school, status="ok", payload=payload)

    @classmethod
    def err(cls, req: "BridgeRequest", code: str,
            message: str) -> "BridgeResponse":
        return cls(id=req.id, school=req.school, status="err", code=code,
                   message=message)

    def to_wire(self) -> dict:
        if self.status == "ok":
            return {"status": "ok", "id": self.id, "school": self.school,
                    "payload": self.payload if self.payload is not None else {}}
        return {"status": "err", "id": self.id, "school": self.school,
                "code": self.code, "message": self.message}


def decode_api_response(frame: dict) -> tuple[int, object]:
    """`ApiResponse` çerçevesini `(status, body)`'ye çevirir."""
    if frame.get("outcome") == "err":
        raise ApiError(f"{frame.get('code', '?')}: {frame.get('message', '')}")
    return int(frame["status"]), frame.get("body")


# ------------------------------------------------- çerçeveleme (protocol.rs)
# `protocol.rs:267-304`: u32 big-endian uzunluk + o kadar bayt JSON. Çerçevenin
# kendisi burada kurulur/çözülür; AKIŞ (kim açar, kim kapatır) taşımanın işi.


def encode_frame(obj) -> bytes:
    """Bir nesneyi tek uzunluk-önekli JSON çerçeveye çevir.

    Boyut tavanı YAZARKEN de uygulanır (`protocol.rs:275-277`): sınırın üstünde
    bir çerçeve yazmak, karşı tarafın okuyamayacağı bir akış bırakmaktır."""
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > AI_MAX_FRAME_BYTES:
        raise FrameTooLarge(len(body))
    return struct.pack(">I", len(body)) + body


class FrameTooLarge(BridgeFrameError):
    """Çerçeve `AI_MAX_FRAME_BYTES` tavanını aşıyor."""

    def __init__(self, size: int) -> None:
        super().__init__(
            f"{size} bayt, {AI_MAX_FRAME_BYTES} baytlık çerçeve sınırını aşıyor",
            "frame_too_large")
        self.size = size


class HandshakeRejected(BridgeFrameError):
    """`Greeting{type:"rejected"}` — backend kaydı reddetti.

    `code` makine okunabilirdir: `unauthorized` / `unsupported_protocol` /
    `no_capabilities` / `malformed` (`server.rs:1030-1046`)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message, code)

    @property
    def permanent(self) -> bool:
        """Yeniden denemek tek başına düzeltir mi? Düzeltmez — ama beklemeyi
        BIRAKMAYIZ (kalıcı rette tavana çekiliriz, çıkmayız)."""
        return self.code in PERMANENT_REJECTS


class FrameStream:
    """Tek bir QUIC akışından çerçeve okuyan tampon.

    `feed()` aioquic'in `StreamDataReceived` olayından beslenir; `read_frame()`
    bir tam çerçeve döndürür. Akış çerçevenin ortasında biterse `EOFError`."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._eof = False

    def feed(self, data: bytes, end: bool) -> None:
        if data:
            self._queue.put_nowait(data)
        if end:
            self._queue.put_nowait(None)

    async def read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            if self._eof:
                raise EOFError("çerçeve tamamlanmadan akış bitti")
            chunk = await self._queue.get()
            if chunk is None:
                self._eof = True
                continue
            self._buf.extend(chunk)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    async def read_frame(self):
        (length,) = struct.unpack(">I", await self.read_exact(4))
        # Uzunluk, gövde AYRILMADAN önce denetlenir (`protocol.rs:286-289`).
        if length > AI_MAX_FRAME_BYTES:
            raise FrameTooLarge(length)
        body = await self.read_exact(length)
        try:
            return json.loads(body)
        except ValueError as exc:
            raise BridgeFrameError(f"çerçeve gövdesi geçerli JSON değil: {exc}") from exc


# ------------------------------------------------------ el sıkışma (kontrol)
# `protocol.rs:85-119`: `Hello` servisten backend'e, `Greeting` backend'den
# servise. `Hello` KASITLI olarak okul TAŞIMAZ: filo paylaşımlıdır, tek bağlantı
# dağıtımdaki her okula hizmet eder ve her `Request` kendi okulunu adlandırır.


def build_hello(service: str, capabilities, token: str,
                max_concurrent: int) -> dict:
    """Kontrol akışına yazılacak `Hello` çerçevesi. Protokol her zaman `hab/2`."""
    return {
        "protocol": AI_PROTOCOL,
        "service": service,
        "capabilities": list(capabilities),
        "token": token,
        "max_concurrent": max(1, min(int(max_concurrent),
                                     AI_MAX_CONCURRENT_PER_WORKER)),
    }


def parse_greeting(raw) -> str:
    """`Greeting`i çöz ve `worker_id` döndür; red ise `HandshakeRejected` atar.

    Etiket alanı `type`, değerler `welcome`/`rejected` (`protocol.rs:106-119`).
    `welcome` gelse bile YANKILANAN protokol denetlenir: eşleşmeyen bir sürümle
    devam etmek, yanlış ayrışacak çerçeveler yazmak demektir."""
    if not isinstance(raw, dict):
        raise HandshakeRejected("malformed", "greeting bir nesne değil")
    kind = raw.get("type")
    if kind == "rejected":
        raise HandshakeRejected(str(raw.get("code") or "malformed"),
                                str(raw.get("message") or ""))
    if kind != "welcome":
        raise HandshakeRejected("malformed", f"bilinmeyen greeting type: {kind!r}")
    yankilanan = str(raw.get("protocol") or "")
    if yankilanan != AI_PROTOCOL:
        raise HandshakeRejected(
            "unsupported_protocol",
            f"backend '{yankilanan}' yankıladı, biz '{AI_PROTOCOL}' konuşuyoruz")
    return str(raw.get("worker_id") or "?")
