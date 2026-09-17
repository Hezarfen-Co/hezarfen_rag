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
AI_RAG_CHAT_CAPABILITY = "rag.chat"      # RAG'e özel kutu (chatbot'tan AYRI)
AI_PROTOCOL = "hab/2"

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


class ApiError(Exception):
    """Köprü düzeyinde red (yol izinli değil, kullanıcı bilinmiyor).

    Koşup 404 dönen bir API çağrısı hata DEĞİLDİR — o `outcome:"ok"` içinde
    kendi durum koduyla gelir (backend'in kendi ifadesi).
    """


def decode_api_response(frame: dict) -> tuple[int, object]:
    """`ApiResponse` çerçevesini `(status, body)`'ye çevirir."""
    if frame.get("outcome") == "err":
        raise ApiError(f"{frame.get('code', '?')}: {frame.get('message', '')}")
    return int(frame["status"]), frame.get("body")
