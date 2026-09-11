"""Faz 1.7a — kaynak-sınırlı üretim + atıf (kaynak yer bulma).
Faz 1.7b — guardrail entegrasyonu (bkz. src/guard/): `answer()` EN BAŞINDA
`check_input` çağrılır (zararlı/injection ise LLM hiç çağrılmadan red);
üretimden SONRA `check_output` çağrılır (üretilen metin zararlıysa cevap red
mesajıyla değiştirilir). Rol-türevli erişim (`RoleContext`/`can_access`)
SUNUCU-TARAFI türetilir (bkz. src/guard/roles.py). Faz 1.6 (commit 299681b, #22)
ile `role_ctx` artık yalnız taşınmıyor: `answer()` onu `retriever.retrieve()`'e
geçirir → yetkisiz sınıf/ders chunk'ları RRF sonrası, trim ÖNCESİ elenir
(bkz. src/retrieve/hybrid.py `_allowed`; `meta` yoksa fail-closed boş sonuç).

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

import os
import re
from dataclasses import dataclass, field, replace

from .. import costlog
from ..guard import check_input, check_output
from ..pricing import Usage, cost_usd as pricing_cost_usd
from ..providers.deepseek import DeepSeek
from ..rerank.pipeline import rerank_select
from .citations import (CITATION_RE, parse_citation_ns, parse_citations,
                        strip_phantom)
from .sentences import citation_coverage, drop_uncited
from .prompt import ABSTAIN_SENTENCE, build_grounded_prompt

# answer(role_ctx=...) için sentinel: "verilmedi → __init__'teki role_ctx'i kullan"
# (None geçerli bir değer: 'rol yok' demek, o yüzden None ile ayrılmalı).
_USE_INIT_ROLE = object()

# Parantez içini yakalar ("1", "1, 2", "1,2" ...); virgül/boşlukla ayrılmış çoklu
# atıfları TEK eşleşmede yakalamak için [\d,\s]+ kullanılır — [1][2] ve [1] [2]
# gibi bitişik/ayrı parantezler ise doğal olarak iki ayrı eşleşme üretir.
# M2-4 (#56, EXP-010/ACC-07) -- CUMLE-BASINA ATIF POLITIKASI.
#
# Urun sozu "cevabin HER cumlesi bir span'a bagli". Kod yalniz
# `if not citations` kontrolu yapiyordu: BIR TEK atif varsa geri kalan tum
# cumleler denetimsiz geciyordu. Kosulan kanit: 5 cumlenin 4'u atifsiz VE
# 3'u olgusal yanlis (47 ATP, ribozom nukleusta, 48 kromozom); sistem bunu
# `abstained=False, reason=''` ile TEMIZ CEVAP olarak dondurdu.
#
# POLITIKA NEDEN VARSAYILAN OLARAK "measure":
# "atif isareti yok" ile "dayanaksiz" AYNI SEY DEGILDIR -- model atifi
# paragraf sonuna koyup onceki cumleleri kapsiyor olabilir. `trim`i olcmeden
# varsayilan yapmak, YANLIS CEKIMSERLIK kapisini (C-03 <=%5) sessizce
# bozabilir. Issue'nun kabul kriteri de ikisinin BIRLIKTE raporlanmasini
# sart kosuyor. Bu yuzden: her zaman OLC, politikayi olcumden sonra sec.
#   off      -> hicbir sey yapma (eski davranis)
#   measure  -> yalniz say (varsayilan)
#   trim     -> atifsiz cumleleri kirp; hic atifli cumle kalmazsa cekimser
#   abstain  -> atifsiz cumle varsa TUM cevabi cekimsere cevir
SENTENCE_POLICY = os.environ.get("RAG_SENTENCE_POLICY", "measure")

_ABSTAIN_MATCH_THRESHOLD = 0.90   # (#58 ile kullanımdan kalktı; geri uyum için duruyor)


@dataclass
class GroundedAnswer:
    text: str
    citations: list = field(default_factory=list)          # [{n, chunk_id, span_ids, pages, ders}]
    used_source_ids: list = field(default_factory=list)    # atıf edilen chunk_id'ler (sırayla)
    invalid_citations: list = field(default_factory=list)  # hayalet [N] numaraları (int listesi)
    # M2-4 (#56, EXP-010/ACC-07) — atıf bütünlüğü ölçümü. Kapı A-03 bunlardan
    # hesaplanır (MVP ≤%10, TAM ≤%1 atıfsız cümle).
    n_sentences: int = 0
    n_cited_sentences: int = 0
    dropped_sentences: list = field(default_factory=list)   # kırpılanlar (politika: trim)
    abstained: bool = False
    reason: str = ""
    usage: Usage | None = None
    cost_usd: float = 0.0
    latency_s: float = 0.0
    cache_hit: bool = False   # True -> ResponseCache'ten döndü, LLM/retrieval HİÇ ÇALIŞMADI


_CITATION_RE = CITATION_RE          # geri uyum (eski içe aktarımlar)
_parse_citation_ns = parse_citation_ns


def _normalize_for_abstain_compare(text: str) -> str:
    """Atıf işaretlerini çıkar + boşluk/noktalama/büyük-küçük harfi normalize et
    (ABSTAIN_SENTENCE ile 'bire bir' karşılaştırma öncesi)."""
    stripped = _CITATION_RE.sub("", text)
    stripped = stripped.strip().lower()
    stripped = re.sub(r"\s+", " ", stripped)
    stripped = stripped.strip(" .!?\"'")
    return stripped


_ABSTAIN_NORM = _normalize_for_abstain_compare(ABSTAIN_SENTENCE)


# M2-6 (#58, EXP-010/ACC-05) — KARAKTER BENZERLIGI BIRAKILDI.
# Eski olcut: difflib.SequenceMatcher orani >= 0.90. Turkcede olumlu/olumsuz ayrimi tek
# ek oldugu icin metrik ANLAMI TERS cumleleri de yakaliyordu (oranlar hesaplandi):
#   "Kaynaklarda bu bilgi bulunamadi."        1,0000  cekimser  DOGRU
#   "Kaynaklarda bu bilgi bulunmaktadir."     0,9231  cekimser  YANLIS (pozitif bastirildi)
#   "Kaynaklarda bu bilgi bulunmaktadir [1]." 0,9231  cekimser  YANLIS (ATIFLI cevap bastirildi)
#   "Kaynaklarda bu bilgi bulunmuyor."        0,8710  cevap     YANLIS (gercek cekimser kacti)
# Yani esik IKI YONDE de yanlisti.
#
# Yeni olcut: tam esitlik + OLUMSUZLUK KOKU. Kritik guvenlik agi zaten
# `if not citations` (temellendirme kapisi) -- bu fonksiyonun agresif olmasina
# gerek YOK; yanlis pozitifi kisa "evet + kaynak var" cevaplarinda recall
# kaybina yol aciyordu.
_ABSTAIN_NEGATIVE_STEMS = (
    "bulunamad", "bulunmuyor", "bulamad", "yer almıyor", "yer almamakta",
    "geçmiyor", "mevcut değil", "yok",
)
# Olumsuzluk koku TEK BASINA yetmez: "DNA cift sarmaldir ama atif yok." cumlesi
# `yok` icerdigi icin cekimser sayiliyordu (testte yakalandi). Cumlenin KAYNAKLAR
# HAKKINDA olmasi da sart -- cekimserlik "kaynakta bulamadim" demektir.
_ABSTAIN_SUBJECT_STEMS = ("kaynak", "kaynakta", "metinde", "belgede", "verilen")


def _looks_like_abstain(text: str) -> bool:
    """Cevap, kaynak-yok cümlesinin bir varyantı mı?

    İki koşul BİRLİKTE aranır (#58):
    1. Normalize edilmiş metin `ABSTAIN_SENTENCE`'a eşit **ya da** onun belirgin
       bir varyantı (aynı özne + olumsuzluk kökü),
    2. metinde **hiç atıf işareti yok** — atıflı bir cevap tanım gereği çekimser
       değildir. (Eskiden "Kaynaklarda bu bilgi bulunmaktadır [1]." bastırılıyordu.)
    """
    norm = _normalize_for_abstain_compare(text)
    if not norm:
        return False
    if norm == _ABSTAIN_NORM:
        return True
    if parse_citation_ns(text):
        return False                      # atıflı cevap çekimser sayılmaz
    if len(norm) > len(_ABSTAIN_NORM) * 2:
        return False                      # uzun, gerçek bir cevap
    return (any(k in norm for k in _ABSTAIN_SUBJECT_STEMS)
            and any(k in norm for k in _ABSTAIN_NEGATIVE_STEMS))


def _is_effectively_empty(text: str) -> bool:
    """Atıf işaretleri + noktalama/boşluk çıkarılınca geriye anlamlı içerik
    kalmıyorsa True (LLM fiilen boş cevap verdi)."""
    stripped = _CITATION_RE.sub("", text)
    stripped = re.sub(r"[\s.,;:!?\"'\-]+", "", stripped)
    return not stripped


def parent_extra(ctx) -> tuple[str, list]:
    """Parent genişletmesinin **child'da OLMAYAN** kısmını ve o kısma ait
    span_id'leri döndürür. Yoksa ("", []).

    M2-2 (#54, EXP-010/ACC-03) — KOŞULARAK KANITLANMIŞ HATA. Eski
    `_source_text_with_parent` parent metnini child kaynağının İÇİNE
    ("Genişletilmiş bağlam: ...") gömüyordu, ama blok başlığındaki sayfa ve
    `source_lookup[i]["pages"]` **yalnız child span'dan** hesaplanıyordu.
    Koşulan kanıt: kaynak bloğu parent üzerinden s.8'deki bilgiyi içeriyordu,
    model o bilgiyi kullanıp `[1]` atıfladı, dönen atıf **s.10** dedi →
    kullanıcı atıfa tıklayınca iddiayı o sayfada BULAMIYOR. Bu, "kaynak yer
    bulma" ürün sözünün doğrudan ihlaliydi. Sıklık düşük değil: parent
    700-1500 token, child 150-300 → parent metninin ~%70'i child dışı.

    Çözüm: parent AYRI numaralı kaynak olur (kendi sayfa aralığıyla) → model
    hangisini kullandığını kendisi atıflar. Child metni parent'tan DÜŞÜLÜR,
    çünkü parent = çocuklarının metinlerinin birleşimidir; düşülmezse aynı
    içerik iki kez token yer ve model geniş sayfa aralıklı parent'ı atıflayıp
    `precision_page`'i düşürebilir (M2-1/#53 ile çakışırdı).
    """
    parent = getattr(ctx, "parent_text", None)
    if not parent or not parent.strip():
        return "", []
    child = (ctx.text or "").strip()
    kalan = parent.replace(child, "\n") if child and child in parent else parent
    kalan = "\n".join(satir for satir in kalan.splitlines() if satir.strip()).strip()
    if not kalan or kalan == child:
        return "", []
    child_spans = set(getattr(ctx, "span_ids", []) or [])
    extra_spans = [sid for sid in (getattr(ctx, "parent_span_ids", []) or [])
                   if sid not in child_spans]
    return kalan, extra_spans


def source_units(ctx) -> list[tuple[str, list]]:
    """Bir context'in prompt'a giren kaynak bloklarını (metin, span_id'ler)
    olarak döndürür: child + varsa ayrı parent genişletmesi.

    TEK KAYNAK: hem `Generator` hem `eval/runner` bunu kullanır. Ayrı ayrı
    kurulsaydı eval ile üretim yine ayrışırdı — ACC-10'da (parent genişletme)
    tam olarak bu olmuştu ve yayınlanmış sayılar üretimi temsil etmemişti.
    """
    bloklar = [(ctx.text, list(getattr(ctx, "span_ids", []) or []))]
    ek_metin, ek_spans = parent_extra(ctx)
    if ek_metin and ek_spans:
        bloklar.append((ek_metin, ek_spans))
    return bloklar


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
                 rewriter=None, corpus_version: str = "", require_role: bool = False):
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
        # sorumlu). Faz 1.6'dan beri retrieval'e GEÇİRİLİR (kasa izolasyonu);
        # istek-başına `answer(role_ctx=...)` ile ezilebilir.
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
        # Kaynak/indeks sürümü (AUDIT #30/M2): cache anahtarına girer → re-ingest
        # sonrası eski cevap dönmesin. Boş "" ise cache davranışı öncekiyle aynı.
        self.corpus_version = corpus_version
        # Çok-kiracılı STRICT mod (AUDIT #31): True ise role_ctx OLMADAN cevap
        # ÜRETİLMEZ (fail-closed) — tek-kasa backward-compat'te role_ctx=None ile
        # filtresiz retrieval "yanlışlıkla açık kasa" riskini kapatır. Varsayılan
        # KAPALI (mevcut tek-kasa davranışı bozulmaz).
        self.require_role = require_role

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

    def _guard_refuse(self, verdict) -> GroundedAnswer:
        """Guard red kararını (regex/LLM/rewrite-sonrası) tek biçimde döndür."""
        return GroundedAnswer(text=verdict.message, citations=[], used_source_ids=[],
                              invalid_citations=[], abstained=True,
                              reason=f"guard_{verdict.category}", usage=None,
                              cost_usd=0.0, latency_s=0.0)

    def _guard_query(self, q: str):
        """q'yu iki katmanla denetle; refuse ise GuardVerdict döner, değilse None.
        Hem orijinal sorgu hem (çok-turlu) rewrite edilmiş sorgu için kullanılır —
        rewrite edilen q retrieval+üretime giren metindir, o yüzden O DA denetlenmeli."""
        gv = check_input(q)
        if gv.action == "refuse":
            return gv
        if self.safety_classifier is not None:
            sv = self.safety_classifier.classify(q)
            if sv.action == "refuse":
                return sv
        return None

    def answer(self, query: str, *, history=None, top_n: int = 6, candidate_n: int = 40,
               max_tokens: int = 700, temperature: float = 0.2, trace=None,
               role_ctx=_USE_INIT_ROLE) -> GroundedAnswer:
        # trace (opsiyonel, #18): karar izi + adım süreleri. None ise ek maliyet YOK.
        def _tr(name, **m):
            if trace is not None:
                trace.event(name, **m)
        # role_ctx istek-başına override (#2 servis çok-kiracılı): verilmezse __init__'teki
        # kullanılır (mevcut davranış). Verilirse retrieval + kasa izolasyonu + cache
        # anahtarı O role'e göre → tek Generator örneği farklı rollere hizmet edebilir.
        eff_role = self.role_ctx if role_ctx is _USE_INIT_ROLE else role_ctx
        # GUARDRAIL (Faz 1.7b) — EN BAŞTA: zararlı-içerik/injection ise LLM'i
        # HİÇ ÇAĞIRMADAN red (reşit-olmayan öğrenci kitlesi; bkz. src/guard/
        # input_guard.py). reason="guard_<kategori>" — çağıran taraf hangi
        # guardrail kategorisinin tetiklendiğini ayırt edebilir.
        # STRICT çok-kiracılı mod (AUDIT #31): role_ctx zorunluysa ve yoksa FAIL-CLOSED
        # (filtresiz retrieval ile kasa sızıntısındansa hiç cevap verme).
        if self.require_role and eff_role is None:
            _tr("decision", stage="role_required", abstained=True, reason="role_required")
            return self._abstain("role_required")

        # İki katman (regex check_input + opsiyonel LLM-sınıflandırıcı) ORİJİNAL
        # sorguda: zararlı/injection ise LLM'i HİÇ çağırmadan red. reason="guard_<kat>".
        gv = self._guard_query(query)
        if gv is not None:
            _tr("decision", stage="guard", abstained=True, reason=f"guard_{gv.category}")
            return self._guard_refuse(gv)

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
            # ÇOK-TURLU BYPASS KAPAMA: rewrite edilmiş q, retrieval + üretim promptuna
            # giren fiili metindir. Zararlı bir niyet geçmişe yayılıp "devam et" gibi
            # zararsız bir turla tetiklenebilir → rewrite SONRASI q'yu da denetle.
            if q != query:
                gv2 = self._guard_query(q)
                if gv2 is not None:
                    return self._guard_refuse(gv2)

        cache_kwargs = None
        if self.response_cache is not None:
            cache_kwargs = dict(query=q, role=_role_cache_key(eff_role),
                                model=getattr(self.deepseek, "model", ""),
                                top_n=top_n, candidate_n=candidate_n, ders=self.ders,
                                corpus_version=self.corpus_version)
            cached = self.response_cache.get(**cache_kwargs)
            if cached is not None:
                self.cache_hits += 1
                self.cache_saved_usd += cached.cost_usd
                _tr("decision", stage="cache", abstained=cached.abstained,
                    reason=cached.reason, cache_hit=True)
                return replace(cached, cache_hit=True, cost_usd=0.0, latency_s=0.0)

        # KASA İZOLASYONU: role_ctx varsa retriever'a geçir (yetkisiz sınıf/ders
        # elenir, bkz. src/retrieve/hybrid.py). role_ctx yoksa eski çağrı (stub/
        # tek-kasa backward-compat).
        if eff_role is not None:
            hits = self.retriever.retrieve(q, top_k=candidate_n, role_ctx=eff_role)
        else:
            hits = self.retriever.retrieve(q, top_k=candidate_n)
        contexts = rerank_select(q, hits, self.chunks_by_id, self.reranker,
                                 top_n=top_n, candidate_n=candidate_n)
        _tr("retrieve", n_hits=len(hits), n_contexts=len(contexts),
            top_score=round(contexts[0].score, 4) if contexts else None,
            abstain_score=self.abstain_score)

        # FAIL-CLOSED: bağlam yok VEYA en iyi rerank skoru eşik altında → LLM ÇAĞIRMA.
        # (skor-azalan sıra üzerinde kontrol — packing'den ÖNCE)
        if not contexts or contexts[0].score < self.abstain_score:
            _tr("decision", stage="fail_closed", abstained=True, reason="insufficient_data")
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
        i = 0
        for ctx in contexts:
            i += 1
            pages = self._pages_for_span_ids(ctx.span_ids)
            numbered_sources.append({"n": i, "ders": self.ders,
                                     "page": _format_pages(pages),
                                     "text": ctx.text})
            source_lookup[i] = {"chunk_id": ctx.chunk_id, "span_ids": list(ctx.span_ids),
                                "pages": pages}
            # #54: parent genişletmesi AYRI numaralı kaynak — kendi sayfasıyla.
            # Child'ın hemen ardında durur ki bağlam kopmasın.
            for ek_metin, ek_spans in source_units(ctx)[1:]:
                ek_pages = self._pages_for_span_ids(ek_spans)
                if not ek_pages:
                    continue          # span_meta'da karşılığı yoksa atıflanamaz
                i += 1
                numbered_sources.append({"n": i, "ders": self.ders,
                                         "page": _format_pages(ek_pages),
                                         "text": ek_metin})
                source_lookup[i] = {"chunk_id": ctx.parent_id or ctx.chunk_id,
                                    "span_ids": list(ek_spans), "pages": ek_pages}

        system, user = build_grounded_prompt(q, numbered_sources)
        result = self.deepseek.chat(user, system=system, temperature=temperature,
                                    max_tokens=max_tokens)

        # cevaptaki [N]/[N,M]/[N][M] atıflarını ayrıştır → gerçek kaynağa eşle (kaynak yer bulma)
        # #57: kaynak sayısı VERİLİR → `[0,1]` gibi veri gösterimleri atıf sanılıp
        # UYDURMA atıf üretmesin. Üç kova döner (bkz. generate/citations.py).
        ham_ns, hayalet_ns, belirsiz_gruplar = parse_citations(result.text,
                                                               len(numbered_sources))
        cited_ns = sorted(set(ham_ns))
        citations = []
        used_source_ids = []
        invalid_citations = sorted(set(hayalet_ns))
        for n in cited_ns:
            src = source_lookup.get(n)
            if src is None:                   # aralık denetimi sonrası olmamalı
                invalid_citations.append(n)
                continue
            citations.append({"n": n, "chunk_id": src["chunk_id"],
                              "span_ids": src["span_ids"], "pages": src["pages"],
                              "ders": self.ders})
            used_source_ids.append(src["chunk_id"])
        invalid_citations = sorted(set(invalid_citations))
        # #62: hayalet `[N]` kullanıcıya gösterilen metinden KIRPILIR — eskiden
        # metinde duruyor ama karşılığında tıklanabilir atıf kaydı olmuyordu.
        # Belirsiz gruplar (`[0,1]`) kırpılmaz: onlar cümlenin içeriği olabilir.
        gosterim_metni = strip_phantom(result.text, invalid_citations)

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

        # #56: ATIF BÜTÜNLÜĞÜ. Ölçüm HER ZAMAN yapılır; politika env'den gelir.
        kapsama = citation_coverage(gosterim_metni)
        n_sent = kapsama["n_sentences"]
        n_cited = kapsama["n_cited_sentences"]
        dropped: list = []
        if citations and SENTENCE_POLICY in ("trim", "abstain") and n_sent > n_cited:
            if SENTENCE_POLICY == "abstain":
                _tr("decision", stage="generate", abstained=True,
                    reason="ungrounded_sentences", n_sentences=n_sent,
                    n_cited_sentences=n_cited)
                return GroundedAnswer(
                    text=ABSTAIN_SENTENCE, citations=[], used_source_ids=[],
                    invalid_citations=invalid_citations, abstained=True,
                    reason="ungrounded_sentences", usage=result.usage, cost_usd=usd,
                    latency_s=result.latency_s, n_sentences=n_sent,
                    n_cited_sentences=n_cited,
                    dropped_sentences=kapsama["uncited_sentences"])
            kirpilmis, dropped = drop_uncited(gosterim_metni)
            if not kirpilmis.strip():
                # Kırpma her şeyi götürdüyse sunulacak bir cevap kalmadı.
                return GroundedAnswer(
                    text=ABSTAIN_SENTENCE, citations=[], used_source_ids=[],
                    invalid_citations=invalid_citations, abstained=True,
                    reason="ungrounded_sentences", usage=result.usage, cost_usd=usd,
                    latency_s=result.latency_s, n_sentences=n_sent,
                    n_cited_sentences=n_cited, dropped_sentences=dropped)
            gosterim_metni = kirpilmis
            # kırpma sonrası atıf listesini metinde GERÇEKTEN kalanlarla daralt
            kalan_ns = set(parse_citation_ns(gosterim_metni, len(numbered_sources)))
            citations = [c for c in citations if c["n"] in kalan_ns]
            used_source_ids = [c["chunk_id"] for c in citations]
            kapsama = citation_coverage(gosterim_metni)
            n_sent, n_cited = kapsama["n_sentences"], kapsama["n_cited_sentences"]

        # post-hoc abstain algılama: cevap kaynak-yok cümlesine çok yakın YA DA
        # (geçerli atıf yok + cevap fiilen boş) → model aslında çekimser kaldı.
        if _looks_like_abstain(result.text) or (not citations and _is_effectively_empty(result.text)):
            return GroundedAnswer(text=gosterim_metni, citations=citations,
                                  used_source_ids=used_source_ids,
                                  invalid_citations=invalid_citations, abstained=True,
                                  reason="model_abstained", usage=result.usage,
                                  cost_usd=usd, latency_s=result.latency_s,
                                  n_sentences=n_sent, n_cited_sentences=n_cited,
                                  dropped_sentences=dropped)

        # TEMELLENDİRME BÜTÜNLÜĞÜ (audit EXP-007 #C1): metin DOLU ama GEÇERLİ ATIF YOK
        # (model [N] hiç emitmedi YA DA hepsi hayalet) → kaynağa bağlanamamış =
        # temellendirilmemiş. Grounded RAG'de böyle bir cevabı kullanıcıya SUNMA;
        # çekimser kal (kaynak-yok cümlesiyle). LLM çağrıldı → cost gerçek; CACHE'LENMEZ.
        # Eskiden atıfsız-ama-dolu cevap "güvenli" sanılıp sunuluyordu.
        if not citations:
            r = "all_citations_phantom" if invalid_citations else "ungrounded_no_citations"
            return GroundedAnswer(text=ABSTAIN_SENTENCE, citations=[], used_source_ids=[],
                                  invalid_citations=invalid_citations, abstained=True,
                                  reason=r, usage=result.usage, cost_usd=usd,
                                  latency_s=result.latency_s)

        final_answer = GroundedAnswer(text=gosterim_metni, citations=citations,
                                      used_source_ids=used_source_ids,
                                      invalid_citations=invalid_citations, abstained=False,
                                      reason=reason, usage=result.usage, cost_usd=usd,
                                      latency_s=result.latency_s,
                                      n_sentences=n_sent, n_cited_sentences=n_cited,
                                      dropped_sentences=dropped)
        _tr("decision", stage="generate", abstained=False, reason=reason or "answer",
            n_citations=len(citations), n_phantom=len(invalid_citations),
            # #56: kapi A-03 bu ikisinden hesaplanir
            n_sentences=n_sent, n_cited_sentences=n_cited,
            # #57 telemetrisi: `[0,1]` gibi belirsiz gruplar atıf sayılmadı.
            # Sıklığı bilinmeden kuralın doğru eşikte olduğu iddia EDİLEMEZ.
            n_belirsiz_grup=len(belirsiz_gruplar),
            cost_usd=round(usd, 6))

        # Yalnız GERÇEK (abstained olmayan) cevaplar cache'e yazılır. FAIL-CLOSED
        # abstain zaten LLM'i hiç çağırmadı (cache'lemenin maliyet kazancı yok);
        # model_abstained/guard_output ise LLM ÇAĞRILDI ama sonuç kullanıcıya
        # ret/çekimser olarak gösterildi — bunları cache'lemek "bu soru bir daha
        # asla cevaplanamaz" diye DONDURUR (retrieval/index/eşik ileride değişebilir)
        # -> BİLİNÇLİ OLARAK cache'lenmez (yalnız buradaki başarılı dönüş yazar).
        if self.response_cache is not None and cache_kwargs is not None:
            self.response_cache.set(final_answer, **cache_kwargs)
        return final_answer
