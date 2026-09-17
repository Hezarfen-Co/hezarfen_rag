"""hab/2 dağıtımı — çerçeveden servise, TAŞIMADAN bağımsız.

Taşıma (QUIC akışları) BURADA DEĞİL. Bu modül bir `Request` çerçevesini alır,
okulunu doğrular, yeteneğe göre servis metoduna yönlendirir ve okulu AYNEN geri
yazan tek bir `Response` üretir. Böylece dağıtım ağ olmadan test edilir —
`BridgeReader`'ın "çerçeveyi kur/çöz, taşımayı dışarıdan ver" ayrımıyla aynı
gerekçe.

OKUL (kiracılık) BU KATMANIN İŞİDİR:
  * Çerçevede okul yoksa → `malformed`, akış DÜŞÜRÜLÜR (`handle` None döner):
    geri yazılacak bir okul yoktur ve backend'in kendi kuralı da "no default,
    no fallback" der.
  * Okul biçimi geçersiz/ayrılmışsa → `invalid_school` tipli reddi (okulun
    VARLIĞI backend'in kararıdır; servis okul listesi icat ETMEZ).
  * Geçerliyse okul servis çağrısının gövdesine AYNEN konur; servis katmanı
    (registry + store) okuma/yazmayı onunla kapsamlar (bkz. guard/tenant.py).
  * Cevap okulu her durumda EKO eder (`BridgeResponse.school`).

`deadline_ms` DÜRÜST SINIR: taşınır ve istek gövdesine konur, ama bu modül
isteği KESEMEZ — boru hattı (retrieval + LLM) senkron çalışır. Son tarihi
zorlamak taşımanın/servis katmanının işidir; sessizce "uyulmuş" sayılmaz.
"""
from __future__ import annotations

from .contract import (AI_CHAT_CAPABILITY, AI_RAG_CHAT_CAPABILITY,
                       AI_RAG_INDEX_CAPABILITY, BridgeFrameError, BridgeRequest,
                       BridgeResponse)

#: Bu depo `rag.index`i HENÜZ sunamaz: dizin yazımı ek dosya BAYTLARINI
#: (`BlobRequest`) ve korpus yönlendirmesini ister; taşıma yazılmadı (BL-010).
#: Sahte bir "tamam" demek yerine tipli reddedilir — backend zaten sessizlik
#: üzerine kurulu (başarısız indeksleme eski `rag_output` satırını korur).
INDEX_UNWIRED = "index_path_unwired"


class Dispatcher:
    """`Request` çerçevesi → servis metodu → `Response` çerçevesi."""

    def __init__(self, service, *, capabilities=None):
        self.service = service
        self.capabilities = tuple(capabilities or (
            AI_CHAT_CAPABILITY, AI_RAG_CHAT_CAPABILITY, AI_RAG_INDEX_CAPABILITY))

    # -- tel biçimi düzeyi ------------------------------------------------
    def handle(self, frame: dict) -> dict | None:
        """Bir `Request` çerçevesini karşılar. Bozuk çerçevede None (akış
        DÜŞER): ekolayacak bir okul/id yoktur, uydurmak protokolü bozar."""
        try:
            req = BridgeRequest.from_wire(frame)
        except BridgeFrameError as e:
            print(f"[kopru][HATA] {e}", flush=True)
            return None
        return self.dispatch(req).to_wire()

    # -- yetenek düzeyi ---------------------------------------------------
    def dispatch(self, req: BridgeRequest) -> BridgeResponse:
        from ..guard.tenant import TenantError, normalize_school
        try:
            okul = normalize_school(req.school)
        except TenantError as e:
            return BridgeResponse.err(req, "invalid_school", str(e))
        if okul is None:
            # Buraya normalde düşülmez: `from_wire` okulsuz çerçeveyi reddeder.
            return BridgeResponse.err(req, "malformed",
                                      "`school` ZORUNLU (varsayılan/fallback yok)")

        if req.capability == AI_RAG_INDEX_CAPABILITY:
            return BridgeResponse.err(
                req, INDEX_UNWIRED,
                "rag.index bu serviste henüz sunulmuyor (taşıma/BLOB yolu "
                "yazılmadı) — istek reddedildi, eski çıktı korunur")
        if req.capability == AI_RAG_CHAT_CAPABILITY:
            return BridgeResponse.ok(req, self._rag_chat(req, okul))
        if req.capability == AI_CHAT_CAPABILITY:
            return BridgeResponse.ok(req, self._chat(req, okul))
        return BridgeResponse.err(
            req, "unsupported_capability",
            f"bu servis `{req.capability}` sunmuyor (yetenekler: "
            f"{', '.join(self.capabilities)})")

    # -- gövde eşlemeleri (tel biçimi → servis sözlüğü) --------------------
    def _govde(self, req: BridgeRequest, okul: str) -> dict:
        """Servis isteğinin ortak alanları: sorgu + ROL + okul.

        Rol backend'de türetilir (`asker_role`); burada ADI eşlenir
        (`role.role`) — bkz. API-CONTRACT §0.2(a). Rol yoksa servis zaten
        fail-closed reddeder (`role_required`)."""
        from .contract import ChatRequestPayload, RagChatRequestPayload
        if req.capability == AI_RAG_CHAT_CAPABILITY:
            p = RagChatRequestPayload.from_wire(req.payload)
            return {"query": p.message, "user": p.asker or None,
                    "role": {"role": p.asker_role} if p.asker_role else None,
                    "scope": [s.to_wire() for s in p.scope],
                    "history": [t.to_wire() for t in p.history],
                    "school": okul, "deadline_ms": req.deadline_ms}
        p = ChatRequestPayload.from_wire(req.payload)
        return {"query": p.message,
                "role": {"role": p.asker_role} if p.asker_role else None,
                "history": [t.to_wire() for t in p.history],
                "school": okul, "deadline_ms": req.deadline_ms}

    def _rag_chat(self, req: BridgeRequest, okul: str) -> dict:
        """`rag.chat` → servis `chat()` → backend'in `RagChatReplyPayload`i."""
        from .contract import RagCitation, RagChatReplyPayload
        cevap = self.service.chat(self._govde(req, okul))
        return RagChatReplyPayload(
            text=str(cevap.get("text") or ""),
            abstained=bool(cevap.get("abstained", False)),
            reason=str(cevap.get("reason") or ""),
            citations=[RagCitation(n=int(c.get("n") or 0),
                                   doc_id=str(c.get("doc_id") or ""),
                                   pages=list(c.get("pages") or []),
                                   span_ids=list(c.get("span_ids") or []),
                                   ders=c.get("ders"))
                       for c in (cevap.get("citations") or [])],
        ).to_wire()

    def _chat(self, req: BridgeRequest, okul: str) -> dict:
        """`chat.reply` → servis `chat()` → backend'in `ChatReplyPayload`i.

        `chat.reply` YALNIZ metin taşır (atıf `rag.chat`e aittir); bu yüzden
        cevap TEK alana indirgenir — fazladan alan göndermek sözleşmeyi
        genişletmek olurdu."""
        cevap = self.service.chat(self._govde(req, okul))
        return {"text": str(cevap.get("text") or "")}
