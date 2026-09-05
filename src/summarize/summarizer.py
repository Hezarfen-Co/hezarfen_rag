"""Özet ÇIKARMA — soru-cevaptan (src/generate/Generator) AYRI mimari.

Fark: kaynak seçimi bir SORU'ya göre hibrit retrieval + rerank ile DEĞİL,
`scope.resolve_scope()`'un döndürdüğü DETERMİNİSTİK kapsamla (sayfa aralığı/
span_id listesi) yapılır (bkz. scope.py). Bu modül YALNIZ kapsamdaki birimlerden
DETAYLI, yapılandırılmış, atıflı ("kanıtlı") bir özet üretir.

Akış: units (kapsam) -> [FAIL-CLOSED: boşsa LLM'i hiç çağırma] -> tek geçiş
(<= max_units_per_group) YA DA hiyerarşik (RAPTOR-benzeri: grupla -> ara-özetle
-> ara-özetleri birleştir) -> `[N]` atıflarını gerçek span_id/sayfaya eşle
("kaynak yer bulma", mimari §0.1) -> costlog'a GERÇEK maliyeti yaz.

Hiyerarşik atıf taşıma: nihai özetteki `[N]`, o N'inci ARA-ÖZETE işaret eder;
ara-özetin KENDİ atıflarındaki ham leaf span_id/sayfa'lar nihai atıfa AYNEN
taşınır (mimari §0.1: atıf HER ZAMAN ham leaf span'da kalır — merge LLM'i asla
yeni bir span/sayfa uydurmaz). Bir ara-özetin geçerli atıfı yoksa (LLM o grupta
hiçbir şeye atıf yapmadıysa) nihai atıf da BOŞ span_ids/pages taşır — sahte
bir kapsam-sayfası ile "doldurulmaz" (pass-bias YASAK: zayıf izlenebilirlik
gizlenmez, olduğu gibi yansır).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import costlog
from ..ingest.canonical import CanonicalUnit
from ..pricing import Usage, cost_usd as pricing_cost_usd
from ..providers.deepseek import DeepSeek
from .prompt import NO_CONTENT_SENTENCE, build_summary_prompt

# generator.py'daki (src/generate/generator.py) [N]/[N,M]/[N][M] atıf ayrıştırma
# deseniyle BİREBİR AYNI davranış — KASITLI kod tekrarı: iki modül birbirinin
# private (alt çizgili) fonksiyonlarına bağlanmasın diye burada yeniden
# tanımlanır. Regex davranışı değişirse HER İKİ modülde de senkron güncellenmeli.
_CITATION_RE = re.compile(r"\[([\d,\s]+)\]")


def _parse_citation_ns(text: str) -> list[int]:
    """`[N]`, `[N, M]`, `[N,M]`, `[N][M]`, `[N] [M]` atıflarının hepsini ayrıştırır."""
    ns: list[int] = []
    for group in _CITATION_RE.findall(text):
        for part in group.split(","):
            part = part.strip()
            if part.isdigit():
                ns.append(int(part))
    return ns


def _format_pages(pages: list[int]) -> str:
    """Sıralı benzersiz sayfa listesini kısa gösterime çevirir (generator.py ile
    aynı biçim): [12] -> "12", [12,13,14] -> "12-14", [12,14] -> "12,14"."""
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


def _sum_usage(usages: list[Usage]) -> Usage:
    """Birden çok gerçek DeepSeek çağrısının token kullanımını TOPLAR (hiyerarşik
    özette grup + birleştirme çağrılarının BİRLEŞİK maliyet/token görünümü için)."""
    return Usage(
        input_cache_hit=sum(u.input_cache_hit for u in usages),
        input_cache_miss=sum(u.input_cache_miss for u in usages),
        output=sum(u.output for u in usages),
        reasoning=sum(u.reasoning for u in usages),
    )


def _chunk_list(items: list, size: int) -> list[list]:
    """`items`'i okuma sırasını KORUYARAK ardışık <= `size` gruplara böler."""
    return [items[i:i + size] for i in range(0, len(items), size)]


@dataclass
class GroundedSummary:
    text: str
    citations: list = field(default_factory=list)   # [{n, span_ids, pages}]
    scope_pages: list = field(default_factory=list)  # kapsamdaki TÜM sayfalar (sıralı, benzersiz)
    n_source_units: int = 0
    abstained: bool = False
    reason: str = ""
    usage: Usage | None = None
    cost_usd: float = 0.0
    latency_s: float = 0.0
    hierarchical: bool = False


class Summarizer:
    """Kapsam-tabanlı (retrieval KULLANMAYAN), atıflı, kanıtlı özet üretimi.

    `max_units_per_group`: tek geçişte LLM'e verilecek AZAMİ birim sayısı. Kapsam
    bunu aşarsa hiyerarşik (RAPTOR-benzeri) moda geçilir (bkz. `_summarize_hierarchical`).
    """

    def __init__(self, deepseek=None, *, module: str = "ozet", cost_recorder=None,
                 max_units_per_group: int = 12):
        self.deepseek = deepseek if deepseek is not None else DeepSeek()
        self.module = module
        # costlog.record varsayılan olarak GERÇEK deftere (Obsidian) yazar; testlerde
        # gerçek dosyayı kirletmemek için enjekte edilebilir (üretimde varsayılan kullanılır).
        self._record = cost_recorder if cost_recorder is not None else costlog.record
        self.max_units_per_group = max_units_per_group

    # ------------------------------------------------------------------ genel

    def _abstain_empty_scope(self) -> GroundedSummary:
        return GroundedSummary(text=NO_CONTENT_SENTENCE, citations=[], scope_pages=[],
                               n_source_units=0, abstained=True, reason="empty_scope",
                               usage=None, cost_usd=0.0, latency_s=0.0, hierarchical=False)

    def summarize(self, units: list[CanonicalUnit], *, scope_label: str = "",
                 max_tokens: int = 1500, temperature: float = 0.3) -> GroundedSummary:
        # FAIL-CLOSED: kapsam boşsa LLM'i HİÇ ÇAĞIRMA (maliyet=0).
        if not units:
            return self._abstain_empty_scope()

        if len(units) <= self.max_units_per_group:
            return self._summarize_single_pass(units, scope_label=scope_label,
                                               max_tokens=max_tokens, temperature=temperature,
                                               hierarchical=False)

        return self._summarize_hierarchical(units, scope_label=scope_label,
                                            max_tokens=max_tokens, temperature=temperature)

    # ------------------------------------------------------------------ ortak

    def _record_call(self, *, usage: Usage, model: str, n_items: int, note: str) -> None:
        self._record(module=self.module, model=model, usage=usage, items=n_items,
                     config={"max_units_per_group": self.max_units_per_group}, note=note)

    # -------------------------------------------------------------- tek geçiş

    def _summarize_single_pass(self, units: list[CanonicalUnit], *, scope_label: str,
                               max_tokens: int, temperature: float,
                               hierarchical: bool) -> GroundedSummary:
        """Kapsamdaki (<= max_units_per_group) birimleri TEK LLM çağrısıyla özetler.

        Hiyerarşik modda ARA-ÖZET üretmek için de kullanılır (`hierarchical` bayrağı
        yalnız dönen `GroundedSummary.hierarchical` alanına yansır — çağrı davranışı
        AYNI)."""
        blocks = []
        source_lookup: dict[int, dict] = {}
        for i, u in enumerate(units, start=1):
            blocks.append({"n": i, "page": u.page, "text": u.text})
            source_lookup[i] = {"span_ids": [u.span_id], "pages": [u.page]}

        system, user = build_summary_prompt(blocks, scope_label)
        result = self.deepseek.chat(user, system=system, temperature=temperature,
                                    max_tokens=max_tokens)

        # cevaptaki [N]/[N,M]/[N][M] atıflarını ayrıştır -> gerçek birime eşle
        # (kaynak yer bulma). Kaynak sayısını aşan [N] -> sessizce elenir (hayalet
        # atıf patlamaya değil sessiz elemeye yol açar, generator.py ile TUTARLI).
        cited_ns = sorted(set(_parse_citation_ns(result.text)))
        citations = []
        for n in cited_ns:
            src = source_lookup.get(n)
            if src is None:
                continue
            citations.append({"n": n, "span_ids": src["span_ids"], "pages": src["pages"]})

        usd = pricing_cost_usd(result.model, result.usage)
        self._record_call(usage=result.usage, model=result.model, n_items=len(units),
                          note=f"özet tek-geçiş: {len(units)} kaynak birimi, "
                               f"{len(citations)} atıflandı")

        scope_pages = sorted({u.page for u in units})
        return GroundedSummary(text=result.text, citations=citations, scope_pages=scope_pages,
                               n_source_units=len(units), abstained=False, reason="",
                               usage=result.usage, cost_usd=usd, latency_s=result.latency_s,
                               hierarchical=hierarchical)

    # ----------------------------------------------------------------- hiyerarşik

    def _summarize_hierarchical(self, units: list[CanonicalUnit], *, scope_label: str,
                                max_tokens: int, temperature: float) -> GroundedSummary:
        """RAPTOR-benzeri: birimleri okuma-sırası koruyarak gruplara böl, her grubu
        AYRI özetle (ara-özet), sonra ara-özetleri BİRLEŞTİRİP nihai detaylı özeti
        üret. Her gerçek DeepSeek çağrısı (grup + birleştirme) ayrı costlog kaydı
        alır; `GroundedSummary.cost_usd` bunların bağımsız (pricing.cost_usd ile
        yeniden hesaplanmış) toplamıdır."""
        groups = _chunk_list(units, self.max_units_per_group)
        group_summaries: list[GroundedSummary] = [
            self._summarize_single_pass(g, scope_label=scope_label, max_tokens=max_tokens,
                                        temperature=temperature, hierarchical=True)
            for g in groups
        ]

        # Ara-özetleri "kaynak" olarak numaralayıp birleştirme promptu kur. Nihai
        # metindeki [N] artık N'inci ARA-ÖZETE işaret eder; o ara-özetin KENDİ
        # atıflarındaki ham leaf span_id/sayfa'lar aşağıda nihai atıfa TAŞINIR
        # (atıf ham leaf span'da kalır, mimari §0.1) — merge adımı asla yeni bir
        # span/sayfa UYDURMAZ.
        merge_blocks = []
        merge_lookup: dict[int, dict] = {}
        for i, gs in enumerate(group_summaries, start=1):
            merge_blocks.append({"n": i, "page": _format_pages(gs.scope_pages), "text": gs.text})
            span_ids = sorted({sid for c in gs.citations for sid in c["span_ids"]})
            pages = sorted({p for c in gs.citations for p in c["pages"]})
            merge_lookup[i] = {"span_ids": span_ids, "pages": pages}

        system, user = build_summary_prompt(merge_blocks, scope_label)
        result = self.deepseek.chat(user, system=system, temperature=temperature,
                                    max_tokens=max_tokens)

        # KANITLI ÖZET bütünlüğü: nihai özet TÜM ara-özetlerin sentezidir; bu yüzden
        # atıf listesi = kanıt üreten HER grubun span/sayfaları (yalnız merge-LLM'in
        # [N]'lediği 1-2 grup DEĞİL — o yaklaşım evidence'ı eksik gösteriyordu: v1
        # testinde 143 birim/12 grup için sadece 2 atıf, biri boştu). Boş-kanıtlı
        # gruplar atlanır (sahte atıf yok). inline [N] hâlâ grup N'e karşılık gelir
        # (n=i tutarlı). Atıf ham leaf span'da kalır (mimari §0.1).
        citations = []
        for i, src in merge_lookup.items():
            if src["span_ids"] or src["pages"]:
                citations.append({"n": i, "span_ids": src["span_ids"], "pages": src["pages"]})

        usd_merge = pricing_cost_usd(result.model, result.usage)
        self._record_call(usage=result.usage, model=result.model, n_items=len(group_summaries),
                          note=f"özet hiyerarşik-birleştirme: {len(group_summaries)} ara-özet "
                               f"({len(units)} kaynak birimi)")

        all_usages = [gs.usage for gs in group_summaries if gs.usage is not None]
        all_usages.append(result.usage)
        total_cost = sum(gs.cost_usd for gs in group_summaries) + usd_merge
        total_latency = sum(gs.latency_s for gs in group_summaries) + result.latency_s
        scope_pages = sorted({u.page for u in units})

        return GroundedSummary(text=result.text, citations=citations, scope_pages=scope_pages,
                               n_source_units=len(units), abstained=False, reason="",
                               usage=_sum_usage(all_usages), cost_usd=total_cost,
                               latency_s=total_latency, hierarchical=True)
