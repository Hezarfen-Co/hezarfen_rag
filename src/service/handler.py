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
    """API role sözlüğü → RoleContext. Tanınmayan/eksik rol → None.

    DİKKAT (#43): `None` "rol yok" demektir, "her şeye erişebilir" DEMEZ.
    Çağıranın bunu fail-CLOSED yorumlaması ZORUNLUDUR (bkz. `_scope_denied`).
    EXP-010/SEC-02'de tam bu yorum hatası vardı: `if role_ctx is not None:`
    koruması yüzünden rol çözülemeyince kontrol TAMAMEN atlanıyordu."""
    if not role or not isinstance(role, dict):
        return None
    try:
        r = Role(str(role.get("role", "")).strip().lower())
    except ValueError:
        return None
    return RoleContext(role=r, sinif=role.get("sinif"),
                       ders_list=list(role.get("ders_list") or []))


# #42/#43 — TEK YETKİ KAPISI (özet + soru yolları). Gerekçe EXP-010:
#   SEC-01 (KRİTİK): erişim kararı istemcinin gönderdiği `scope.sinif`/`scope.ders`
#     ile veriliyordu → saldırgan `can_access`'e hem özneyi hem NESNEYİ kendisi
#     bildiriyordu. Koşularak kanıtlandı: 9. sınıf matematik öğrencisi gerçek
#     rolüyle `scope={"sinif":"9","ders":"matematik"}` gönderip 12-biyoloji
#     içeriğini özetletti.
#   SEC-02 (KRİTİK): rol çözülemezse (`manager` enum'da yok, `"Öğrenci"`, boş)
#     kontrol tamamen atlanıyordu (fail-OPEN).
# Çözüm: kapsamın sınıf/dersi YALNIZ sunucu gerçeğinden (`self.doc`) alınır;
# istemcinin bildirdiği değer varsa DOĞRULAMA GİRDİSİ değil, sunucu gerçeğiyle
# EŞLEŞME ŞARTI olarak kullanılır (uyuşmazsa red). Rol yoksa red.
def _scope_denied(service, scope: dict, role: dict | None) -> str | None:
    """Yetki reddi gerekçesi ya da None (erişim serbest).

    Dönen değerler: "role_required" | "role_denied" | "scope_mismatch" | None
    """
    role_ctx = _role_ctx(role)
    if role_ctx is None:
        return "role_required"            # fail-CLOSED (#43)
    # SUNUCU GERÇEĞİ — istemci bunu değiştiremez (#42)
    srv_sinif = getattr(service.doc, "sinif", None)
    srv_ders = service.ders or getattr(service.doc, "ders", None)
    # İstemci kapsam etiketi gönderdiyse sunucu gerçeğiyle EŞLEŞMELİ; yoksa red.
    cli_sinif, cli_ders = scope.get("sinif"), scope.get("ders")
    if cli_sinif is not None and str(cli_sinif) != str(srv_sinif):
        return "scope_mismatch"
    if cli_ders is not None and str(cli_ders) != str(srv_ders):
        return "scope_mismatch"
    if not can_access(role_ctx, sinif=srv_sinif, ders=srv_ders):
        return "role_denied"
    return None


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
        # ERİŞİM YENİDEN DOĞRULAMA (API-CONTRACT §4) — #42/#43: karar YALNIZ
        # sunucu gerçeğinden; rol yoksa fail-closed.
        denied = _scope_denied(self, scope, req.get("role"))
        if denied:
            return {"text": "", "abstained": True, "reason": denied,
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
        denied = _scope_denied(self, scope, req.get("role"))
        if denied:
            return {"items": [], "abstained": True, "reason": denied,
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
