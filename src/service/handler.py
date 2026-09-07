"""Faz — RAG servis isteği işleyici (#2, transport-BAĞIMSIZ). API-CONTRACT.md'deki
/rag/chat + /rag/summarize + /rag/questions girdi/çıktı sözleşmesini uygular; JSON-
uyumlu dict alır/döner. HTTP sunucusu VEYA backend QUIC köprüsü bunu sarar (D3
kararı transport'ta; iş mantığı + rol-uygulaması + biçimleme burada — tek yer).

GÜVENLİK (RES-002/003): `role` SUNUCU-TARAFI türetilmiş kabul edilir (transport/auth
katmanı üretir; bu handler onu OLDUĞU GİBİ uygular, doğrulamaz). role verilmişse
kasa izolasyonu Generator.answer(role_ctx=...) ile; özet kapsamı için de erişim
yeniden doğrulanır (yanlış sınıf/ders → red)."""
from __future__ import annotations

from ..guard.roles import RoleContext, Role, can_access


def _role_ctx(role: dict | None):
    """API role sözlüğü → RoleContext. Tanınmayan/eksik rol → None (no-leak: çağıran
    strict modda ise Generator fail-closed olur)."""
    if not role or not isinstance(role, dict):
        return None
    try:
        r = Role(str(role.get("role", "")).strip().lower())
    except ValueError:
        return None
    return RoleContext(role=r, sinif=role.get("sinif"),
                       ders_list=list(role.get("ders_list") or []))


def _answer_to_dict(a) -> dict:
    return {
        "text": a.text,
        "abstained": bool(a.abstained),
        "reason": a.reason or "",
        "citations": [{"n": c.get("n"), "chunk_id": c.get("chunk_id"),
                       "span_ids": c.get("span_ids", []), "pages": c.get("pages", []),
                       "ders": c.get("ders", "")} for c in a.citations],
        "used_source_ids": list(a.used_source_ids),
        "cost_usd": round(a.cost_usd, 6),
        "cache_hit": bool(getattr(a, "cache_hit", False)),
    }


class RagService:
    """Bir korpus için RAG servisi: chat (generator) + özet (doc+summarizer) +
    benzer-soru (question_gen). Bileşenler enjekte edilir (index/model paylaşılır)."""

    def __init__(self, generator, *, doc=None, summarizer=None, question_gen=None,
                 ders: str = ""):
        self.generator = generator
        self.doc = doc
        self.summarizer = summarizer
        self.question_gen = question_gen
        self.ders = ders

    # ------------------------------------------------------------------ /rag/chat
    def chat(self, req: dict) -> dict:
        query = (req.get("query") or "").strip()
        if not query:
            return {"text": "", "abstained": True, "reason": "empty_query",
                    "citations": [], "used_source_ids": [], "cost_usd": 0.0, "cache_hit": False}
        role_ctx = _role_ctx(req.get("role"))
        opts = req.get("options") or {}
        a = self.generator.answer(
            query, history=req.get("history"),
            top_n=int(opts.get("top_n", 6)), candidate_n=int(opts.get("candidate_n", 40)),
            role_ctx=role_ctx)
        return _answer_to_dict(a)

    # -------------------------------------------------------------- /rag/summarize
    def summarize(self, req: dict) -> dict:
        if self.doc is None or self.summarizer is None:
            return {"text": "", "abstained": True, "reason": "summary_unavailable",
                    "citations": [], "scope_pages": [], "hierarchical": False, "cost_usd": 0.0}
        scope = req.get("scope") or {}
        pages = scope.get("pages")
        span_ids = scope.get("span_ids")
        if not pages and not span_ids:
            return {"text": "", "abstained": True, "reason": "empty_scope",
                    "citations": [], "scope_pages": [], "hierarchical": False, "cost_usd": 0.0}
        # ERİŞİM YENİDEN DOĞRULAMA (API-CONTRACT §4): rol verilmişse kapsamın ders/
        # sınıfına erişebilmeli — aksi halde red (kasa izolasyonu özet yolunda da).
        role_ctx = _role_ctx(req.get("role"))
        if role_ctx is not None:
            sinif = scope.get("sinif") or getattr(self.doc, "sinif", None)
            ders = scope.get("ders") or self.ders or getattr(self.doc, "ders", None)
            if not can_access(role_ctx, sinif=sinif, ders=ders):
                return {"text": "", "abstained": True, "reason": "role_denied",
                        "citations": [], "scope_pages": [], "hierarchical": False, "cost_usd": 0.0}
        from ..summarize.scope import resolve_scope
        units = resolve_scope(self.doc, pages=pages, span_ids=span_ids)
        res = self.summarizer.summarize(units, scope_label=scope.get("scope_label", ""))
        return {
            "text": res.text, "abstained": bool(res.abstained), "reason": res.reason or "",
            "citations": [{"n": c.get("n"), "span_ids": c.get("span_ids", []),
                           "pages": c.get("pages", [])} for c in res.citations],
            "scope_pages": res.scope_pages, "hierarchical": bool(res.hierarchical),
            "cost_usd": round(res.cost_usd, 6),
        }

    # -------------------------------------------------------------- /rag/questions
    def generate_questions(self, req: dict) -> dict:
        if self.doc is None or self.question_gen is None:
            return {"items": [], "abstained": True, "reason": "questions_unavailable",
                    "span_ids": [], "pages": [], "cost_usd": 0.0}
        scope = req.get("scope") or {}
        pages, span_ids = scope.get("pages"), scope.get("span_ids")
        role_ctx = _role_ctx(req.get("role"))
        if role_ctx is not None:
            sinif = scope.get("sinif") or getattr(self.doc, "sinif", None)
            ders = scope.get("ders") or self.ders or getattr(self.doc, "ders", None)
            if not can_access(role_ctx, sinif=sinif, ders=ders):
                return {"items": [], "abstained": True, "reason": "role_denied",
                        "span_ids": [], "pages": [], "cost_usd": 0.0}
        from ..summarize.scope import resolve_scope
        units = resolve_scope(self.doc, pages=pages, span_ids=span_ids)
        res = self.question_gen.generate(units, n=int(req.get("n", 5)),
                                         difficulty=req.get("difficulty", "orta"),
                                         seed_question=req.get("seed_question"))
        return {
            "items": [{"soru": q.soru, "cevap": q.cevap, "zorluk": q.zorluk} for q in res.items],
            "abstained": bool(res.abstained), "reason": res.reason or "",
            "span_ids": res.span_ids, "pages": res.pages, "cost_usd": round(res.cost_usd, 6),
        }
