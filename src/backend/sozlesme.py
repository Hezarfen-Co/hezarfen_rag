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

from dataclasses import dataclass, field, asdict

# --- yetenek adları (constant.rs) ---
AI_CHAT_CAPABILITY = "chat.reply"
AI_RAG_INDEX_CAPABILITY = "rag.index"
AI_PROTOCOL = "hab/2"

# Backend'in kabul ettiği okul rolleri (domain/role.rs — `ai` ATANAMAZ).
ATANABILIR_ROLLER = ("parent", "student", "teacher", "manager", "admin")


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


class ApiHata(Exception):
    """Köprü düzeyinde red (yol izinli değil, kullanıcı bilinmiyor).

    Koşup 404 dönen bir API çağrısı hata DEĞİLDİR — o `outcome:"ok"` içinde
    kendi durum koduyla gelir (backend'in kendi ifadesi).
    """


def api_cevabini_coz(frame: dict) -> tuple[int, object]:
    """`ApiResponse` çerçevesini `(status, body)`'ye çevirir."""
    if frame.get("outcome") == "err":
        raise ApiHata(f"{frame.get('code', '?')}: {frame.get('message', '')}")
    return int(frame["status"]), frame.get("body")
