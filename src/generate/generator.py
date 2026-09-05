"""Faz 1.7a — kaynak-sınırlı üretim + atıf (kaynak yer bulma).
Faz 1.7b — guardrail entegrasyonu (bkz. src/guard/): `answer()` EN BAŞINDA
`check_input` çağrılır (zararlı/injection ise LLM hiç çağrılmadan red);
üretimden SONRA `check_output` çağrılır (üretilen metin zararlıysa cevap red
mesajıyla değiştirilir). Rol-türevli erişim (`RoleContext`/`can_access`)
SUNUCU-TARAFI türetilir (bkz. src/guard/roles.py) — opsiyonel `role_ctx`
burada yalnız TAŞINIR; retrieval-seviyesi filtre Faz 1.6 kapsamındadır, bu
generator HENÜZ retrieval'i role_ctx'e göre filtrelemez (ileriki hook).

Akış: [guard: check_input] → hibrit retrieval (1.4) → rerank + parent
genişletme (1.5) → FAIL-CLOSED eşiği (kanıt yetersizse LLM'i hiç ÇAĞIRMA,
çekimser dön) → kaynak-sınırlı prompt (prompt.py) → DeepSeek → [guard:
check_output] → cevaptaki `[N]` atıflarını gerçek kaynağa (chunk_id +
span_ids + sayfa + bbox) eşle → costlog'a gerçek maliyeti yaz.

"Kaynak yer bulma": her `[N]` yalnız bir metin parçasına değil, `span_meta`
üzerinden gerçek SAYFA (+ bbox) numarasına bağlanır — kullanıcı atıfı kaynak
PDF'te bulabilsin (mimari §0.1: cevap ham leaf span'lara bağlı).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher

from .. import costlog
from ..guard import check_input, check_output
from ..pricing import Usage, cost_usd as pricing_cost_usd
from ..providers.deepseek import DeepSeek
from ..rerank.pipeline import rerank_select
from .prompt import ABSTAIN_SENTENCE, build_grounded_prompt

# Parantez içini yakalar ("1", "1, 2", "1,2" ...); virgül/boşlukla ayrılmış çoklu
# atıfları TEK eşleşmede yakalamak için [\d,\s]+ kullanılır — [1][2] ve [1] [2]
# gibi bitişik/ayrı parantezler ise doğal olarak iki ayrı eşleşme üretir.
_CITATION_RE = re.compile(r"\[([\d,\s]+)\]")

_ABSTAIN_MATCH_THRESHOLD = 0.90   # normalize edilmiş cevap ~ ABSTAIN_SENTENCE benzerliği


@dataclass
class GroundedAnswer:
    text: str
    citations: list = field(default_factory=list)          # [{n, chunk_id, span_ids, pages, ders}]
    used_source_ids: list = field(default_factory=list)    # atıf edilen chunk_id'ler (sırayla)
    invalid_citations: list = field(default_factory=list)  # hayalet [N] numaraları (int listesi)
    abstained: bool = False
    reason: str = ""
    usage: Usage | None = None
    cost_usd: float = 0.0
    latency_s: float = 0.0
    cache_hit: bool = False   # True -> ResponseCache'ten döndü, LLM/retrieval HİÇ ÇALIŞMADI


def _parse_citation_ns(text: str) -> list[int]:
    """Metindeki `[N]`, `[N, M]`, `[N,M]`, `[N][M]`, `[N] [M]` atıflarının hepsini
    ayrıştırır: parantez içini yakala (`[\\d,\\s]+`), virgülle böl, int'e çevir."""
    ns: list[int] = []
    for group in _CITATION_RE.findall(text):
        for part in group.split(","):
            part = part.strip()
            if part.isdigit():
                ns.append(int(part))
    return ns


def _normalize_for_abstain_compare(text: str) -> str:
    """Atıf işaretlerini çıkar + boşluk/noktalama/büyük-küçük harfi normalize et
    (ABSTAIN_SENTENCE ile 'bire bir' karşılaştırma öncesi)."""
    stripped = _CITATION_RE.sub("", text)
    stripped = stripped.strip().lower()
    stripped = re.sub(r"\s+", " ", stripped)
    stripped = stripped.strip(" .!?\"'")
    return stripped


_ABSTAIN_NORM = _normalize_for_abstain_compare(ABSTAIN_SENTENCE)


def _looks_like_abstain(text: str) -> bool:
    """Cevap, prompt'taki kaynak-yok cümlesine (ABSTAIN_SENTENCE) eşit ya da çok
    yakın mı? (post-hoc abstain algılama — model FAIL-CLOSED eşiğini geçti ama
    fiilen kaynaksız olduğunu kendi söyledi)."""
    norm = _normalize_for_abstain_compare(text)
    if not norm:
        return False
    if norm == _ABSTAIN_NORM:
        return True
    return SequenceMatcher(None, norm, _ABSTAIN_NORM).ratio() >= _ABSTAIN_MATCH_THRESHOLD


def _is_effectively_empty(text: str) -> bool:
    """Atıf işaretleri + noktalama/boşluk çıkarılınca geriye anlamlı içerik
    kalmıyorsa True (LLM fiilen boş cevap verdi)."""
    stripped = _CITATION_RE.sub("", text)
    stripped = re.sub(r"[\s.,;:!?\"'\-]+", "", stripped)
    return not stripped


def _source_text_with_parent(ctx) -> str:
    """Child (leaf) metnini + varsa parent genişletmesini AYRI, NET biçimde
    birleştirir. Atıf/sayfa YİNE child span'dan hesaplanır (mimari §0.1: cevap
    ham leaf span'lara bağlı) — parent yalnız LLM'e ek bağlam sağlar."""
    text = ctx.text
    parent = getattr(ctx, "parent_text", None)
    if parent and parent.strip() and parent.strip() != text.strip():
        text = f"{text}\n\nGenişletilmiş bağlam: {parent}"
    return text


def build_span_meta(canonical_doc) -> dict:
    """CanonicalDoc.units'tan span_id -> {page, bbox} sözlüğü (atıf → sayfa/konum).

    Generator, RerankedContext.span_ids'i bu sözlükle çözüp her `[N]` atıfını
    gerçek sayfa numarasına bağlar ("kaynak yer bulma")."""
    return {u.span_id: {"page": u.page, "bbox": u.bbox} for u in canonical_doc.units}


def _format_pages(pages: list[int]) -> str:
    """Sıralı benzersiz sayfa listesini kısa gösterime çevir: [12] -> "12",
    [12,13,14] -> "12-14", [12,14] -> "12,14"."""
    if not pages:
        return "?"
    parts: list[str] = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = p
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(parts)


def _role_cache_key(role_ctx) -> str:
    """role_ctx (opsiyonel `RoleContext`, bkz. src/guard/roles.py) -> ResponseCache
    anahtarına giren STABİL metin. Duck-typing kullanılır (generator, guard.roles'a
    sıkı bağlanmaz) — `role_ctx` yoksa/tanınmıyorsa boş string (herkese ortak
    "rolsüz" anahtar; role_ctx None iken zaten davranış aynı).

    RagArt'ın client-header karışıklığına düşmemek için: rol FARKLIYSA (ör.
    student vs teacher, ya da farklı `ders_list`) aynı soru bile FARKLI cache
    anahtarına düşer — aksi halde bir rolün cache'lenmiş cevabı başka bir role
    sızabilirdi (bkz. src/cache/response_cache.py modül docstring'i)."""
    if role_ctx is None:
        return ""
    role = getattr(role_ctx, "role", None)
    role_str = str(getattr(role, "value", role)) if role is not None else ""
    sinif = getattr(role_ctx, "sinif", None) or ""
    ders_list = sorted(getattr(role_ctx, "ders_list", None) or [])
    return f"{role_str}:{sinif}:{','.join(ders_list)}"


class Generator:
    """Kaynak-sınırlı üretim: retrieve → rerank → FAIL-CLOSED eşiği → grounded LLM → atıf eşleme."""

    def __init__(self, retriever, reranker, chunks_by_id, span_meta, deepseek=None, *,
                 ders: str = "", abstain_score: float = 0.30, module: str = "chat",
                 cost_recorder=None, role_ctx=None, response_cache=None,
                 safety_classifier=None, context_packing: bool = False,
                 context_max_tokens: int = 8000, context_reorder: bool = True,
                 rewriter=None):
        self.retriever = retriever
        self.reranker = reranker
        self.chunks_by_id = chunks_by_id
        self.span_meta = span_meta
        self.deepseek = deepseek if deepseek is not None else DeepSeek()
        self.ders = ders
        # PROVİZYONEL eşik — golden set (Faz 1.8) sonrası kalibre edilecek.
        self.abstain_score = abstain_score
        self.module = module
        # costlog.record varsayılan olarak GERÇEK deftere (Obsidian) yazar; testlerde
        # gerçek dosyayı kirletmemek için enjekte edilebilir (üretimde varsayılan kullanılır).
        self._record = cost_recorder if cost_recorder is not None else costlog.record
        # Opsiyonel — SUNUCU-TARAFI türetilmiş RoleContext (bkz. src/guard/roles.py).
        # İSTEMCİ header'ından ASLA doğrudan kurulmamalı (çağıran taraf/auth katmanı
        # sorumlu). Şu an yalnız TAŞINIR; retrieval-seviyesi filtre Faz 1.6 hook'u.
        self.role_ctx = role_ctx
        # Opsiyonel ResponseCache (bkz. src/cache/response_cache.py). None ise
        # davranış ÖNCEKİYLE BİREBİR AYNI (mevcut testler bozulmaz). Hit olursa
        # `answer()` LLM/retrieval'i HİÇ ÇALIŞTIRMAZ (bkz. aşağı).
        self.response_cache = response_cache
        # Cache telemetrisi (RES-002 §4 — RagArt'ın boşluğu: canlı $ ölçümü yoktu).
        # Cache hit'te DeepSeek'e GERÇEKTEN gidilmediği için costlog.record'a
        # yazacak gerçek token/usage YOK; sıfır-usage'lı bir "run" eklemek
        # Maliyet.md'nin birim-maliyet tablosunu (asılsız $0 ile) BOZAR — bu yüzden
        # hit sayısı + tahmini tasarruf burada AYRI, hafif sayaçlarla tutulur.
        self.cache_hits = 0
        self.cache_saved_usd = 0.0
        # Opsiyonel LLM güvenlik sınıflandırıcı (2. katman, bkz. src/guard/
        # llm_classifier.py). None ise atlanır (regex check_input tek katman
        # kalır). Duck-typed: .classify(query) -> GuardVerdict bekler.
        self.safety_classifier = safety_classifier
        # Context engineering (opsiyonel, bkz. src/context/packing.py): token
        # bütçesi + lost-in-the-middle sıralama. Varsayılan KAPALI (mevcut davranış
        # korunur); eval/üretim açar. Atıf/span değişmez.
        self.context_packing = context_packing
        self.context_max_tokens = context_max_tokens
        self.context_reorder = context_reorder
        # Opsiyonel history-aware query rewriter (çok-turlu hafıza, bkz.
        # src/memory/history_rewrite.py). None ise/geçmiş yoksa atlanır. Duck-typed:
        # .rewrite(history, query) -> str.
        self.rewriter = rewriter

    def _pages_for_span_ids(self, span_ids: list[str]) -> list[int]:
        pages = []
        for sid in span_ids:
            meta = self.span_meta.get(sid)
            if meta and meta.get("page") is not None:
                pages.append(meta["page"])
        return sorted(set(pages))

    def _abstain(self, reason: str) -> GroundedAnswer:
        return GroundedAnswer(text=ABSTAIN_SENTENCE, citations=[],
                              used_source_ids=[], abstained=True, reason=reason,
                              usage=None, cost_usd=0.0, latency_s=0.0)

    def answer(self, query: str, *, history=None, top_n: int = 6, candidate_n: int = 40,
               max_tokens: int = 700, temperature: float = 0.2) -> GroundedAnswer:
        # GUARDRAIL (Faz 1.7b) — EN BAŞTA: zararlı-içerik/injection ise LLM'i
        # HİÇ ÇAĞIRMADAN red (reşit-olmayan öğrenci kitlesi; bkz. src/guard/
        # input_guard.py). reason="guard_<kategori>" — çağıran taraf hangi
        # guardrail kategorisinin tetiklendiğini ayırt edebilir.
        guard_verdict = check_input(query)
        if guard_verdict.action == "refuse":
            return GroundedAnswer(text=guard_verdict.message, citations=[],
                                  used_source_ids=[], invalid_citations=[],
                                  abstained=True, reason=f"guard_{guard_verdict.category}",
                                  usage=None, cost_usd=0.0, latency_s=0.0)

        # 2. KATMAN — LLM güvenlik sınıflandırıcı (opsiyonel): regex'in kaçırdığı
        # parafraz/dolaylı zararlıyı yakalar (baseline: e05/e06 regex'i atlatmıştı;
        # bkz. src/guard/llm_classifier.py). DeepSeek maliyeti costlog'a (module=
        # guard) yazılır; red ise retrieval/üretim HİÇ çalışmaz.
        if self.safety_classifier is not None:
            sv = self.safety_classifier.classify(query)
            if sv.action == "refuse":
                return GroundedAnswer(text=sv.message, citations=[],
                                      used_source_ids=[], invalid_citations=[],
                                      abstained=True, reason=f"guard_{sv.category}",
                                      usage=None, cost_usd=0.0, latency_s=0.0)

        # CACHE (Faz — maliyet optimizasyonu, opsiyonel) — guard'dan SONRA,
        # retrieval/LLM'den ÖNCE: hit varsa LLM/retrieval'i HİÇ ÇALIŞTIRMADAN
        # cache'teki GroundedAnswer'ı dön (cost_usd=0.0 GERÇEKTEN sıfır — DeepSeek'e
        # ağ çağrısı YAPILMADI). Anahtar cevabı değiştirebilecek HER parametreyi
        # içerir (bkz. src/cache/response_cache.py) — RagArt'ın "eksik parametre ->
        # yanlış cache hit" tuzağına düşmemek için.
        #
        # Guard red kararları BURAYA HİÇ ULAŞMAZ (yukarıda erken dönüldü) -> guard
        # sonuçları KASITLI olarak cache'lenmez: LLM zaten çağrılmadığı için ek bir
        # maliyet kazancı yok, üstelik guardrail kuralları zamanla değişebilir —
        # donmuş bir red/allow kararını cache'lemek güvenlik riskini büyütür.
        # HAFIZA — history-aware query rewrite (çok-turlu): takip sorusunu (zamir/
        # eksilti) BAĞIMSIZ sorguya çevir → retrieval + cache + üretim BUNU (`q`)
        # kullanır (bkz. src/memory/history_rewrite.py). Geçmiş yok / rewriter yoksa
        # `q == query` (davranış değişmez). Guard ORİJİNAL sorguyu denetledi (yukarıda);
        # rewrite ondan SONRA — kullanıcının fiilen yazdığı denetlenir, retrieval ise
        # çözülmüş bağımsız sorguyla yapılır.
        q = query
        if history and self.rewriter is not None:
            q = self.rewriter.rewrite(history, query)

        cache_kwargs = None
        if self.response_cache is not None:
            cache_kwargs = dict(query=q, role=_role_cache_key(self.role_ctx),
                                model=getattr(self.deepseek, "model", ""),
                                top_n=top_n, candidate_n=candidate_n, ders=self.ders)
            cached = self.response_cache.get(**cache_kwargs)
            if cached is not None:
                self.cache_hits += 1
                self.cache_saved_usd += cached.cost_usd
                return replace(cached, cache_hit=True, cost_usd=0.0, latency_s=0.0)

        hits = self.retriever.retrieve(q, top_k=candidate_n)
        contexts = rerank_select(q, hits, self.chunks_by_id, self.reranker,
                                 top_n=top_n, candidate_n=candidate_n)

        # FAIL-CLOSED: bağlam yok VEYA en iyi rerank skoru eşik altında → LLM ÇAĞIRMA.
        # (skor-azalan sıra üzerinde kontrol — packing'den ÖNCE)
        if not contexts or contexts[0].score < self.abstain_score:
            return self._abstain("insufficient_data")

        # CONTEXT ENGINEERING (opsiyonel): token bütçesi + lost-in-the-middle sıralama
        # (bkz. src/context/packing.py). Atıf/span değişmez; yalnız sıra + dahil edilen
        # context'ler. fail-closed'dan SONRA, numaralı kaynaklardan ÖNCE.
        if self.context_packing:
            from ..context import pack_contexts
            contexts = pack_contexts(contexts, max_tokens=self.context_max_tokens,
                                     reorder=self.context_reorder)

        # kaynakları numarala + span_meta'dan gerçek sayfa(lar)ı çıkar; her kaynağın
        # metnine (varsa) parent genişletmesini ayrı, net biçimde ekle (yalnız bağlam
        # — atıf/sayfa child span'dan hesaplanır, aşağıda değişmez)
        numbered_sources = []
        source_lookup = {}
        for i, ctx in enumerate(contexts, start=1):
            pages = self._pages_for_span_ids(ctx.span_ids)
            numbered_sources.append({"n": i, "ders": self.ders,
                                     "page": _format_pages(pages),
                                     "text": _source_text_with_parent(ctx)})
            source_lookup[i] = {"chunk_id": ctx.chunk_id, "span_ids": list(ctx.span_ids),
                                "pages": pages}

        system, user = build_grounded_prompt(q, numbered_sources)
        result = self.deepseek.chat(user, system=system, temperature=temperature,
                                    max_tokens=max_tokens)

        # cevaptaki [N]/[N,M]/[N][M] atıflarını ayrıştır → gerçek kaynağa eşle (kaynak yer bulma)
        cited_ns = sorted(set(_parse_citation_ns(result.text)))
        citations = []
        used_source_ids = []
        invalid_citations = []
        for n in cited_ns:
            src = source_lookup.get(n)
            if src is None:
                invalid_citations.append(n)   # kaynak sayısını aşan [N] — patlamadan işaretle
                continue
            citations.append({"n": n, "chunk_id": src["chunk_id"],
                              "span_ids": src["span_ids"], "pages": src["pages"],
                              "ders": self.ders})
            used_source_ids.append(src["chunk_id"])

        if invalid_citations and not citations:
            reason = "all_citations_phantom"    # [N] var ama HİÇBİRİ geçerli değil
        elif invalid_citations:
            reason = "phantom_citation"         # bazıları geçerli, bazıları hayalet
        else:
            reason = ""

        usd = pricing_cost_usd(result.model, result.usage)
        # LLM GERÇEKTEN çağrıldı → maliyet gerçek; aşağıdaki post-hoc abstain kontrolü
        # yalnız `abstained` bayrağını/`reason`'ı düzeltir, cost_usd'yi SIFIRLAMAZ.
        self._record(module=self.module, model=result.model, usage=result.usage, items=1,
                     config={"top_n": top_n, "candidate_n": candidate_n},
                     note=f"grounded-answer: {len(citations)}/{len(contexts)} kaynak atıflandı")

        # GUARDRAIL (Faz 1.7b) — üretimden SONRA: girdi guard'ı geçse bile
        # LLM'in ÜRETTİĞİ metin zararlı olabilir (ince ikinci savunma katmanı,
        # bkz. src/guard/output_guard.py). LLM GERÇEKTEN çağrıldığı için
        # usage/cost_usd GERÇEK kalır (sıfırlanmaz) — yalnız kullanıcıya
        # gösterilecek metin + atıflar red mesajıyla değiştirilir.
        output_verdict = check_output(result.text)
        if output_verdict.action == "refuse":
            return GroundedAnswer(text=output_verdict.message, citations=[],
                                  used_source_ids=[], invalid_citations=[],
                                  abstained=True, reason="guard_output",
                                  usage=result.usage, cost_usd=usd,
                                  latency_s=result.latency_s)

        # post-hoc abstain algılama: cevap kaynak-yok cümlesine çok yakın YA DA
        # (geçerli atıf yok + cevap fiilen boş) → model aslında çekimser kaldı.
        if _looks_like_abstain(result.text) or (not citations and _is_effectively_empty(result.text)):
            return GroundedAnswer(text=result.text, citations=citations,
                                  used_source_ids=used_source_ids,
                                  invalid_citations=invalid_citations, abstained=True,
                                  reason="model_abstained", usage=result.usage,
                                  cost_usd=usd, latency_s=result.latency_s)

        final_answer = GroundedAnswer(text=result.text, citations=citations,
                                      used_source_ids=used_source_ids,
                                      invalid_citations=invalid_citations, abstained=False,
                                      reason=reason, usage=result.usage, cost_usd=usd,
                                      latency_s=result.latency_s)

        # Yalnız GERÇEK (abstained olmayan) cevaplar cache'e yazılır. FAIL-CLOSED
        # abstain zaten LLM'i hiç çağırmadı (cache'lemenin maliyet kazancı yok);
        # model_abstained/guard_output ise LLM ÇAĞRILDI ama sonuç kullanıcıya
        # ret/çekimser olarak gösterildi — bunları cache'lemek "bu soru bir daha
        # asla cevaplanamaz" diye DONDURUR (retrieval/index/eşik ileride değişebilir)
        # -> BİLİNÇLİ OLARAK cache'lenmez (yalnız buradaki başarılı dönüş yazar).
        if self.response_cache is not None and cache_kwargs is not None:
            self.response_cache.set(final_answer, **cache_kwargs)
        return final_answer
