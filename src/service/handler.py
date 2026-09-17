"""Faz — RAG servis isteği işleyici (#2, transport-BAĞIMSIZ). API-CONTRACT.md'deki
/rag/chat + /rag/summarize + /rag/questions girdi/çıktı sözleşmesini uygular; JSON-
uyumlu dict alır/döner. HTTP sunucusu VEYA backend QUIC köprüsü bunu sarar (D3
kararı transport'ta; iş mantığı + rol-uygulaması + biçimleme burada — tek yer).

GÜVENLİK (RES-002/003): `role` SUNUCU-TARAFI türetilmiş kabul edilir (transport/auth
katmanı üretir; bu handler onu OLDUĞU GİBİ uygular, doğrulamaz). role verilmişse
kasa izolasyonu Generator.answer(role_ctx=...) ile; özet kapsamı için de erişim
yeniden doğrulanır (yanlış sınıf/ders → red)."""
from __future__ import annotations

from ..budget import BudgetGate, check_request_size
from ..observability.trace import RequestTrace, redact, write_trace
from ..providers.resilience import LlmUnavailable
from ..guard.roles import RoleContext, Role, can_access


def scope_pairs(scope) -> list:
    """İstekteki `scope`'u (sınıf, ders) ÇİFT listesine indirger.

    İki biçim kabul edilir — YENİ `[{sinif, ders}, ...]` (rag.chat) ve eski
    `{"sinif": ..., "ders": ...}` sözlüğü (özet/soru yolu). Sözlük biçimi tek
    çift verir; `sinif`/`ders` yoksa boş liste. Sıra korunur.

    NEDEN ÇİFT: bkz. `bridge/contract.RagScopePair` (çapraz-çarpım güvenliği).
    """
    if isinstance(scope, (list, tuple)):
        out = []
        for p in scope:
            if isinstance(p, dict) and p.get("ders"):
                s = p.get("sinif")
                out.append((str(s) if s not in (None, "") else None, str(p["ders"])))
            elif hasattr(p, "ders"):
                out.append((p.sinif, p.ders))
        return out
    if isinstance(scope, dict):
        d = scope.get("ders")
        if d:
            s = scope.get("sinif")
            return [(str(s) if s not in (None, "") else None, str(d))]
    return []


def _role_ctx(role: dict | None, scope=None):
    """API role sözlüğü → RoleContext. Tanınmayan/eksik rol → None.

    DİKKAT (#43): `None` "rol yok" demektir, "her şeye erişebilir" DEMEZ.
    Çağıranın bunu fail-CLOSED yorumlaması ZORUNLUDUR (bkz. `_scope_denied`).
    EXP-010/SEC-02'de tam bu yorum hatası vardı: `if role_ctx is not None:`
    koruması yüzünden rol çözülemeyince kontrol TAMAMEN atlanıyordu.

    KAPSAM (çift listesi): `scope` bir (sınıf, ders) çift listesi ise
    (`scope_pairs`) role'ün `sinif`/`ders_list` ALANLARINDAN ÖNCE gelir — backend
    artık kapsamı bu biçimde gönderiyor. Eski `sinif`+`ders_list` biçimi
    GERİYE UYUMLU çalışmaya devam eder. `sinif`/`ders_list` burada, çiftlerden
    türetilirken KARTEZYEN ÇARPIMA DÜŞÜLMEZ: yalnız tüm çiftlerin paylaştığı
    ortak sınıf yazılır (paylaşılan sınıf yoksa None); asgari düzeyde ayrıcalık
    verilir, hiçbir (sınıf,ders) çifti yanlışlıkla AÇILMAZ.
    """
    if not role or not isinstance(role, dict):
        return None
    try:
        r = Role(str(role.get("role", "")).strip().lower())
    except ValueError:
        return None
    # GÜVENLİK: yalnız ÇİFT LİSTESİ yetki GRANT'i sayılır. Özet/soru yolunun
    # sözlük `scope`'u istemci-beyanlı bir EŞLEŞME girdisidir (SEC-01) — ondan
    # grant türetmek client'ın özneyi kendisi bildirmesi demek olurdu.
    pairs = scope_pairs(scope) if isinstance(scope, (list, tuple)) else []
    if pairs:
        sinifler = {s for s, _ in pairs}
        ortak = next(iter(sinifler)) if len(sinifler) == 1 else None
        return RoleContext(role=r, sinif=ortak, ders_list=[d for _, d in pairs],
                           scope_pairs=list(pairs))
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



# #78 (EXP-010/OPS-06) — LLM ARIZASI TIPLI CEVABA CEVRILIR.
# Olculdu: stub 429 ile `RagService.chat` istisnayi yakalamiyor, FastAPI'de
# global handler da yok -> yanit HTTP 500, govde "Internal Server Error"
# (reason yok, request_id yok, retry-after yok). Backend ise `abstained/reason`
# sozlesmesine gore yazilmis; bu govdeyi PARSE EDEMIYOR.
LLM_UNAVAILABLE_TEXT = ("Şu anda cevap üretemiyorum; yapay zekâ servisine "
                        "ulaşılamıyor. Birazdan tekrar dener misin?")


BUDGET_TEXT = ("Bugünkü kullanım sınırına ulaşıldı. Yarın tekrar "
               "deneyebilirsin.")
SCOPE_TEXT = ("Seçtiğin bölüm bir seferde özetlenemeyecek kadar geniş. "
              "Daha dar bir aralık seçer misin?")


def _budget_denied(karar, kind: str = "chat") -> dict:
    """Bütçe/kapsam reddi — API-CONTRACT uyumlu, TÜRKÇE mesajlı."""
    metin = SCOPE_TEXT if karar.reason == "scope_too_large" else BUDGET_TEXT
    ortak = {"abstained": True, "reason": karar.reason, "text": metin,
             "cost_usd": 0.0}
    if kind == "chat":
        return {**ortak, "citations": [], "used_source_ids": [],
                "invalid_citations": [], "cache_hit": False}
    if kind == "ozet":
        return {**ortak, "citations": [], "scope_pages": [], "hierarchical": False}
    return {**ortak, "items": [], "span_ids": [], "pages": []}


def _llm_unavailable(kind: str = "chat") -> dict:
    """Saglayici arizasi icin API-CONTRACT uyumlu cevap."""
    ortak = {"abstained": True, "reason": "llm_unavailable",
             "text": LLM_UNAVAILABLE_TEXT, "cost_usd": 0.0}
    if kind == "chat":
        return {**ortak, "citations": [], "used_source_ids": [],
                "invalid_citations": [], "cache_hit": False}
    if kind == "ozet":
        return {**ortak, "citations": [], "scope_pages": [], "hierarchical": False}
    return {**ortak, "items": []}


def _answer_to_dict(a) -> dict:
    return {
        "text": a.text,
        "abstained": bool(a.abstained),
        "reason": a.reason or "",
        "citations": [{"n": c.get("n"), "chunk_id": c.get("chunk_id"),
                       "span_ids": c.get("span_ids", []), "pages": c.get("pages", []),
                       "ders": c.get("ders", ""), "doc_id": c.get("doc_id", "")}
                      for c in a.citations],
        "used_source_ids": list(a.used_source_ids),
        # #62 (EXP-010/ACC-12): hayalet `[N]` numaralari payload'a HIC girmiyordu.
        # Metinden kirpilsa bile backend'in "bu cevapta cozulemeyen atif vardi"
        # bilgisine erisimi olmali (telemetri + kalite kapisi O-?/A-*).
        "invalid_citations": list(getattr(a, "invalid_citations", []) or []),
        "cost_usd": round(a.cost_usd, 6),
        "cache_hit": bool(getattr(a, "cache_hit", False)),
    }


class RagService:
    """Bir korpus için RAG servisi: chat (generator) + özet (doc+summarizer) +
    benzer-soru (question_gen). Bileşenler enjekte edilir (index/model paylaşılır)."""

    def __init__(self, generator, *, doc=None, summarizer=None, question_gen=None,
                 ders: str = "", budget: BudgetGate | None = None):
        self.generator = generator
        # #79 (EXP-010/OPS-05): maliyet tavanı. `costlog.record()` yalnız
        # YAZIYORDU; hiçbir çağıran dönüş değerine bakıp reddetmiyordu.
        self.budget = budget if budget is not None else BudgetGate()
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
        role_ctx = _role_ctx(req.get("role"), req.get("scope"))
        karar = self.budget.check(user=req.get("user"), tenant=req.get("tenant"))
        if not karar.allowed:
            return _budget_denied(karar, "chat")
        opts = req.get("options") or {}
        # #85 (EXP-010/OPS-12): iz URETIMDE HIC URETILMIYORDU. `trace=`
        # gecirilmedigi icin generator'daki butun `_tr()` cagrilari no-op'tu ve
        # "neden bu cevabi verdi?" sorusu geriye donuk cevaplanamiyordu.
        # Sorgu METNI ize YAZILMAZ (#49/KVKK) -- yalniz uzunluk + kisa hash.
        trace = RequestTrace(request_id=req.get("request_id"))
        trace.event("request", kind="chat", query=redact(query),
                    role=(role_ctx.role.value if role_ctx else None),
                    sinif=(role_ctx.sinif if role_ctx else None),
                    top_n=int(opts.get("top_n", 6)),
                    candidate_n=int(opts.get("candidate_n", 40)))
        try:
            a = self.generator.answer(
                query, history=req.get("history"),
                top_n=int(opts.get("top_n", 6)),
                candidate_n=int(opts.get("candidate_n", 40)),
                role_ctx=role_ctx, trace=trace)
        except LlmUnavailable:
            trace.event("error", kind="llm_unavailable")
            write_trace(trace)
            return _llm_unavailable("chat")
        # Harcama GERÇEKLEŞTİ → sayaca yaz. Kapı bir sonraki istekte bakar;
        # harcamadan sonra bakmak tavanı anlamsız kılardı.
        self.budget.record(getattr(a, "cost_usd", 0.0) or 0.0,
                           user=req.get("user"), tenant=req.get("tenant"))
        trace.event("response", abstained=bool(a.abstained), reason=a.reason or "",
                    n_citations=len(a.citations),
                    n_sentences=getattr(a, "n_sentences", 0),
                    n_cited_sentences=getattr(a, "n_cited_sentences", 0),
                    n_phantom=len(getattr(a, "invalid_citations", []) or []),
                    cache_hit=bool(getattr(a, "cache_hit", False)),
                    cost_usd=round(a.cost_usd, 6))
        write_trace(trace)
        out = _answer_to_dict(a)
        out["request_id"] = trace.request_id       # #85: yanita KOY
        return out

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
        # #79: tek istekte yüzlerce LLM çağrısı olmasın. Ölçülen sömürü:
        # `scope.pages=[1..187]` → 19 çağrı (özyinelemeli hiyerarşik mod).
        from ..chunk.chunker import approx_tokens
        boyut = check_request_size(
            len(units),
            n_tokens=sum(approx_tokens(getattr(u, "text", "") or "") for u in units),
            max_units_per_group=getattr(self.summarizer, "max_units_per_group", 12))
        if not boyut.allowed:
            return _budget_denied(boyut, "ozet")
        karar = self.budget.check(user=req.get("user"), tenant=req.get("tenant"))
        if not karar.allowed:
            return _budget_denied(karar, "ozet")
        try:
            res = self.summarizer.summarize(units,
                                            scope_label=scope.get("scope_label", ""))
        except LlmUnavailable:
            return _llm_unavailable("ozet")
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
        karar = self.budget.check(user=req.get("user"), tenant=req.get("tenant"))
        if not karar.allowed:
            return _budget_denied(karar, "soru")
        try:
            res = self.question_gen.generate(
                units, n=int(req.get("n", 5)),
                difficulty=req.get("difficulty", "orta"),
                seed_question=req.get("seed_question"))
        except LlmUnavailable:
            bos = _llm_unavailable("soru")
            return {**bos, "span_ids": [], "pages": []}
        return {
            "items": [{"soru": q.soru, "cevap": q.cevap, "zorluk": q.zorluk} for q in res.items],
            "abstained": bool(res.abstained), "reason": res.reason or "",
            "span_ids": res.span_ids, "pages": res.pages, "cost_usd": round(res.cost_usd, 6),
        }
