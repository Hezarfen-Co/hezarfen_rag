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
from ..generate.citations import CITATION_RE, parse_citation_ns
from .prompt import NO_CONTENT_SENTENCE, build_summary_prompt

# #57: bu mantık eskiden burada AYRI bir kopyaydı ve yorumu "KASITLI kod tekrarı
# ... regex davranışı değişirse HER İKİ modülde de senkron güncellenmeli" diyordu.
# Böyle bir senkron sözü kodda tutulmaz (ACC-10'da tam bu şekilde ayrışmıştı),
# bu yüzden tek kaynağa taşındı.
_CITATION_RE = CITATION_RE
_parse_citation_ns = parse_citation_ns


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
            res = self._summarize_single_pass(units, scope_label=scope_label,
                                              max_tokens=max_tokens, temperature=temperature,
                                              hierarchical=False)
        else:
            res = self._summarize_hierarchical(units, scope_label=scope_label,
                                               max_tokens=max_tokens, temperature=temperature)
        return self._guard_output(res)

    # #46 (EXP-010/SEC-05): bu yolun ciktisi `check_output`tan HIC gecmiyordu
    # (grep: check_output yalniz generator.py'da cagriliyordu). Yani ogretmenin
    # yukledigi kaynaga gomulu zararli icerik ya da modelin uretttigi zararli
    # metin ozet yuzeyinden hicbir denetime takilmadan ogrenciye gidiyordu.
    def _guard_output(self, res: GroundedSummary) -> GroundedSummary:
        from ..guard import check_output
        v = check_output(res.text)
        if v.action != "refuse":
            return res
        # Maliyet GERCEK (LLM cagrildi) -> korunur; metin ve atiflar dusurulur.
        return GroundedSummary(text=v.message, citations=[], scope_pages=res.scope_pages,
                               abstained=True, reason=f"guard_{v.category}",
                               hierarchical=res.hierarchical, usage=res.usage,
                               cost_usd=res.cost_usd, latency_s=res.latency_s)

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
        cited_ns = sorted(set(_parse_citation_ns(result.text, len(units))))   # #57
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
        # AUDIT EXP-007 #C2: model prompt gereği "içerik yok" cümlesini dönerse bu bir
        # ÇEKİMSER'dir — abstained=True işaretle (çağıran .abstained'e bakıp gerçek özet
        # sanmasın). Eskiden yalnız BOŞ kapsam abstained sayılıyordu.
        llm_abstained = result.text.strip() == NO_CONTENT_SENTENCE
        return GroundedSummary(text=result.text, citations=citations, scope_pages=scope_pages,
                               n_source_units=len(units),
                               abstained=llm_abstained,
                               reason="llm_no_content" if llm_abstained else "",
                               usage=result.usage, cost_usd=usd, latency_s=result.latency_s,
                               hierarchical=hierarchical)

    # ----------------------------------------------------------------- hiyerarşik

    def _merge_summaries(self, summaries: list[GroundedSummary], *, scope_label: str,
                         max_tokens: int, temperature: float) -> GroundedSummary:
        """Ara-özet listesini TEK DeepSeek çağrısıyla birleştir. Nihai metindeki [N]
        i'inci ara-özete işaret eder; o ara-özetin atıflarındaki ham leaf span_id/
        sayfa'lar nihai atıfa AYNEN taşınır (atıf leaf'te kalır, mimari §0.1 — merge
        yeni span/sayfa UYDURMAZ). Boş-kanıtlı ara-özetler atıfta atlanır (sahte yok)."""
        merge_blocks = []
        merge_lookup: dict[int, dict] = {}
        for i, gs in enumerate(summaries, start=1):
            merge_blocks.append({"n": i, "page": _format_pages(gs.scope_pages), "text": gs.text})
            span_ids = sorted({sid for c in gs.citations for sid in c["span_ids"]})
            pages = sorted({p for c in gs.citations for p in c["pages"]})
            merge_lookup[i] = {"span_ids": span_ids, "pages": pages}
        system, user = build_summary_prompt(merge_blocks, scope_label)
        result = self.deepseek.chat(user, system=system, temperature=temperature,
                                    max_tokens=max_tokens)
        # M2-3 (#55, EXP-010/ACC-01) -- KOSULARAK KANITLANMIS HATA:
        # burada `_parse_citation_ns(result.text)` CAGRILMIYORDU; `citations`
        # dogrudan `merge_lookup.items()`'tan, yani KANITI OLAN TUM ara-ozetlerden
        # uretiliyordu. Kosulan kanit: 9 birim / mupg=3 -> 3 ara-ozet; model nihai
        # metinde YALNIZ [1] atifladi, cikti 3 atif dondu (s.1, s.4, s.7).
        # s.4 ve s.7 MODELIN YAPMADIGI atiflardi. Docstring "merge yeni span/sayfa
        # uydurmaz" diyordu -- dogru, ama KOD uyduruyordu. Ozet yuzeyinde atif
        # precision'i yapisal olarak 1/grup_sayisi'na dusuyordu.
        # Cozum tek-gecis yolundaki desenin AYNISI: yalniz atiflanan N'ler.
        cited_ns = sorted(set(_parse_citation_ns(result.text, len(summaries))))  # #57
        citations = []
        for n in cited_ns:
            src = merge_lookup.get(n)
            if src is None:                      # hayalet atif -> sessiz eleme
                continue
            if not (src["span_ids"] or src["pages"]):
                continue                         # kaniti olmayan ara-ozet
            citations.append({"n": n, "span_ids": src["span_ids"], "pages": src["pages"]})
        usd = pricing_cost_usd(result.model, result.usage)
        self._record_call(usage=result.usage, model=result.model, n_items=len(summaries),
                          note=f"özet hiyerarşik-birleştirme: {len(summaries)} ara-özet, "
                               f"{len(citations)} atıflandı")
        scope_pages = sorted({p for gs in summaries for p in gs.scope_pages})
        # #55 (ikinci yari): `abstained=False` SABITTI -> nihai merge
        # NO_CONTENT_SENTENCE donse bile "gercek ozet" isaretleniyordu.
        llm_abstained = result.text.strip() == NO_CONTENT_SENTENCE
        return GroundedSummary(text=result.text, citations=citations, scope_pages=scope_pages,
                               n_source_units=sum(gs.n_source_units for gs in summaries),
                               abstained=llm_abstained,
                               reason="llm_no_content" if llm_abstained else "",
                               usage=result.usage,
                               cost_usd=usd, latency_s=result.latency_s, hierarchical=True)

    def _summarize_hierarchical(self, units: list[CanonicalUnit], *, scope_label: str,
                                max_tokens: int, temperature: float) -> GroundedSummary:
        """RAPTOR-proper (ÖZYİNELEMELİ, AUDIT EXP-007 #30/M6): birimleri gruplara böl →
        her grubu ara-özetle → ara-özet sayısı `max_units_per_group`'u AŞTIĞI sürece
        onları da gruplayıp özyinelemeli birleştir → tek nihai özet. Böylece HİÇBİR
        birleştirme çağrısı `max_units_per_group`'tan fazla blok almaz (eskiden tek
        merge tüm grupları alıyordu → çok büyük kapsamda context taşması riski).
        Maliyet/usage/latency TÜM seviyelerin toplamıdır; atıf her seviyede leaf'te kalır."""
        mupg = self.max_units_per_group
        groups = _chunk_list(units, mupg)
        level: list[GroundedSummary] = [
            self._summarize_single_pass(g, scope_label=scope_label, max_tokens=max_tokens,
                                        temperature=temperature, hierarchical=True)
            for g in groups
        ]
        all_usages = [gs.usage for gs in level if gs.usage is not None]
        total_cost = sum(gs.cost_usd for gs in level)
        total_latency = sum(gs.latency_s for gs in level)

        # ara-özet sayısı 1'e inene dek özyinelemeli birleştir (her turda ≤ mupg'lik gruplar)
        while len(level) > 1:
            new_level: list[GroundedSummary] = []
            for chunk in _chunk_list(level, mupg):
                merged = self._merge_summaries(chunk, scope_label=scope_label,
                                               max_tokens=max_tokens, temperature=temperature)
                new_level.append(merged)
                if merged.usage is not None:
                    all_usages.append(merged.usage)
                total_cost += merged.cost_usd
                total_latency += merged.latency_s
            level = new_level

        final = level[0]
        # #55: burada da `abstained=False` SABITTI -- son seviyenin cekimserligi
        # (tek grup varsa tek-gecisin, coksa merge'in) yutuluyordu.
        return GroundedSummary(text=final.text, citations=final.citations,
                               scope_pages=sorted({u.page for u in units}),
                               n_source_units=len(units),
                               abstained=final.abstained, reason=final.reason,
                               usage=_sum_usage(all_usages), cost_usd=total_cost,
                               latency_s=total_latency, hierarchical=True)
