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
                       AI_RAG_INDEX_CAPABILITY, AI_RAG_QUESTIONS_CAPABILITY,
                       AI_RAG_SUMMARIZE_CAPABILITY, BridgeFrameError, BridgeRequest,
                       BridgeResponse)

# `rag.index` is served end to end: the payload is parsed, every attachment is
# read as bytes over its own blob stream, the note is chunked, embedded and
# written into the school's note index (`service::notes_index`), and the answer
# object goes back for the backend to store as the note's `rag_output`.
class Dispatcher:
    """`Request` çerçevesi → servis metodu → `Response` çerçevesi."""

    def __init__(self, service, *, capabilities=None, indexer=None):
        self.service = service
        #: `rag.index`'in gövdesi (not → parça → gömme → not indeksi). Enjekte
        #: edilebilir: taşıma testleri ağ/örnek istemeyen bir sahte verir;
        #: üretimde `service::notes_index.index_course_note` koşar.
        self.indexer = indexer
        #: Blob okuyucusu — TAŞIMA takar (`transport.BridgeTransport.register`).
        #: Yoksa ekler okunamaz ve notun kendi metni yine indekslenir.
        self.blob_reader = None
        self.capabilities = tuple(capabilities or (
            AI_CHAT_CAPABILITY, AI_RAG_CHAT_CAPABILITY, AI_RAG_INDEX_CAPABILITY,
            AI_RAG_SUMMARIZE_CAPABILITY, AI_RAG_QUESTIONS_CAPABILITY))

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
            return self._rag_index(req, okul)
        if req.capability == AI_RAG_CHAT_CAPABILITY:
            return BridgeResponse.ok(req, self._rag_chat(req, okul))
        if req.capability == AI_RAG_SUMMARIZE_CAPABILITY:
            return BridgeResponse.ok(req, self._rag_summarize(req, okul))
        if req.capability == AI_RAG_QUESTIONS_CAPABILITY:
            return BridgeResponse.ok(req, self._rag_questions(req, okul))
        if req.capability == AI_CHAT_CAPABILITY:
            return BridgeResponse.ok(req, self._chat(req, okul))
        return BridgeResponse.err(
            req, "unsupported_capability",
            f"bu servis `{req.capability}` sunmuyor (yetenekler: "
            f"{', '.join(self.capabilities)})")

    # -- gövde eşlemeleri (tel biçimi → servis sözlüğü) --------------------
    def _rag_index(self, req: BridgeRequest, okul: str) -> BridgeResponse:
        """`rag.index` → not + ekler → not indeksi → backend'in sakladığı gövde.

        Redler TİPLİ ve küçük tutulur: backend bir hatada eski `rag_output`
        satırını korur, yani "sessiz tamam" en kötü sonuçtur. Tek bir ekin
        okunamaması ise red DEĞİLDİR — notun kendi metni indekslenir ve cevap
        hangi ekin okunamadığını söyler (bkz. `service/notes_index.py`)."""
        from .contract import RagIndexPayload
        try:
            payload = RagIndexPayload.from_wire(req.payload)
        except (KeyError, TypeError) as exc:
            return BridgeResponse.err(req, "malformed",
                                      f"rag.index gövdesi eksik/yanlış: {exc}")
        indexer = self.indexer
        if indexer is None:
            from ..service.notes_index import index_course_note as indexer
        try:
            cevap = indexer(payload, school=okul, blob_reader=self.blob_reader)
        except Exception as exc:                        # noqa: BLE001
            import traceback
            traceback.print_exc()
            return BridgeResponse.err(req, "internal",
                                      f"rag.index çalıştırılamadı: "
                                      f"{type(exc).__name__}: {exc}")
        if not isinstance(cevap, dict):
            return BridgeResponse.err(req, "internal",
                                      "rag.index bir nesne döndürmedi")
        return BridgeResponse.ok(req, cevap)

    def _govde(self, req: BridgeRequest, okul: str) -> dict:
        """Servis isteğinin ortak alanları: sorgu + ROL + okul.

        Rol backend'de türetilir (`asker_role`); burada ADI eşlenir
        (`role.role`) — bkz. API-CONTRACT §0.2(a). Rol yoksa servis zaten
        fail-closed reddeder (`role_required`)."""
        from .contract import ChatRequestPayload, RagChatRequestPayload
        if req.capability in (AI_RAG_SUMMARIZE_CAPABILITY,
                              AI_RAG_QUESTIONS_CAPABILITY):
            return self._govde_kapsam(req, okul)
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

    def _govde_kapsam(self, req: BridgeRequest, okul: str) -> dict:
        """`rag.summarize`/`rag.questions` servis isteği — `rag.chat`ten AYRI.

        `scope_pairs`, backend'in çağıran için hesapladığı grant listesidir ve
        özet/soru yetki kapısına aynen aktarılır. Alanın boş olması eski
        backend'lerin gönderdiği gövdelerde legacy role kapsamına düşürür.
        """
        from .contract import (RagQuestionsRequestPayload,
                               RagSummarizeRequestPayload)
        if req.capability == AI_RAG_QUESTIONS_CAPABILITY:
            p = RagQuestionsRequestPayload.from_wire(req.payload)
            ek = {"n": p.n, "difficulty": p.difficulty,
                  "seed_question": p.seed_question}
        else:
            p = RagSummarizeRequestPayload.from_wire(req.payload)
            ek = {}
        return {"scope": p.scope.to_wire(), "user": p.asker or None,
                "role": ({"role": p.asker_role, "sinif": p.scope.sinif,
                          "ders_list": [p.scope.ders]} if p.asker_role else None),
                "scope_pairs": list(p.scope_pairs),
                "school": okul, "deadline_ms": req.deadline_ms, **ek}

    def _rag_summarize(self, req: BridgeRequest, okul: str) -> dict:
        """`rag.summarize` → servis `summarize()` → backend'in `RagSummarizeReplyPayload`i."""
        from .contract import RagSummarizeReplyPayload, RagSummaryCitation
        cevap = self.service.summarize(self._govde(req, okul))
        return RagSummarizeReplyPayload(
            text=str(cevap.get("text") or ""),
            abstained=bool(cevap.get("abstained", False)),
            reason=str(cevap.get("reason") or ""),
            citations=[RagSummaryCitation(n=int(c.get("n") or 0),
                                          span_ids=list(c.get("span_ids") or []),
                                          pages=list(c.get("pages") or []))
                       for c in (cevap.get("citations") or [])],
            scope_pages=list(cevap.get("scope_pages") or []),
            hierarchical=bool(cevap.get("hierarchical", False)),
        ).to_wire()

    def _rag_questions(self, req: BridgeRequest, okul: str) -> dict:
        """`rag.questions` → servis `generate_questions()` → backend DTO'su.

        Soru satırının anahtarları servisin kendi sözlüğüdür (`soru`/`cevap`/
        `zorluk`) ve AYNEN taşınır; yeniden adlandırma backend'in işidir."""
        from .contract import RagQuestion, RagQuestionsReplyPayload
        cevap = self.service.generate_questions(self._govde(req, okul))
        return RagQuestionsReplyPayload(
            items=[RagQuestion(soru=str(i.get("soru") or ""),
                               cevap=str(i.get("cevap") or ""),
                               zorluk=str(i.get("zorluk") or ""))
                   for i in (cevap.get("items") or [])],
            abstained=bool(cevap.get("abstained", False)),
            reason=str(cevap.get("reason") or ""),
            span_ids=list(cevap.get("span_ids") or []),
            pages=list(cevap.get("pages") or []),
        ).to_wire()

    def _chat(self, req: BridgeRequest, okul: str) -> dict:
        """`chat.reply` → servis `chat()` → backend'in `ChatReplyPayload`i.

        `chat.reply` YALNIZ metin taşır (atıf `rag.chat`e aittir); bu yüzden
        cevap TEK alana indirgenir — fazladan alan göndermek sözleşmeyi
        genişletmek olurdu."""
        cevap = self.service.chat(self._govde(req, okul))
        return {"text": str(cevap.get("text") or "")}
