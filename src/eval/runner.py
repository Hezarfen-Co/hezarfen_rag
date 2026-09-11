"""Faz 1.8 / OPTIMIZATION.md §A — eval runner.

Golden set'e (tests/golden/golden_12bio_v0.json — TASLAK, bkz. README.md
"benchmark kilidi") karsi TAM pipeline'i (canonical -> chunk -> embed -> index
-> hibrit retrieval -> rerank -> Generator -> guard -> span_meta) BIR KEZ
kurar, her item icin deterministik metrikleri (src.eval.metrics) + secili
item'larda LLM-hakem metriklerini (src.eval.judge, DeepEval+DeepSeek) hesaplar,
kategori bazinda + genel aggregate + en zayif item'lari raporlar.

PASS-BIAS YASAK (docs/OPTIMIZATION.md sub A): bu betik "gecirmeye" calismaz,
ham sayilari oldugu gibi yazar. Golden set bir TASLAKTIR (Kadir onayi
bekliyor) -- buradaki sayilar nihai kabul olcusu DEGILDIR.

CALISTIRMA:
    PYTHONPATH="." .venv/Scripts/python.exe -m src.eval.runner

.env: DEEPSEEK_API_KEY .env dosyasindan os.environ'a yuklenir (zaten set
degilse); DEGER ASLA loglanmaz/yazdirilmaz.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

from .. import costlog
from ..chunk import chunk_document
from ..embed import BGEM3Embedder
from ..generate import Generator, build_span_meta
from ..generate.generator import _source_text_with_parent
from ..index import DenseIndex, BM25Index
from ..ingest.canonical import build_canonical
from ..providers.deepseek import DeepSeek
from ..rerank import BGEReranker, rerank_select
from ..retrieve import SparseIndex, HybridRetriever
from . import metrics as M
from .judge import LlmJudge, JUDGE_METHOD, DEEPEVAL_AVAILABLE

# Varsayılan v1 (190 item, TASLAK); GOLDEN_PATH env değişkeniyle override edilebilir.
GOLDEN_PATH = os.environ.get(
    "GOLDEN_PATH", os.path.join("tests", "golden", "golden_12bio_v1.json"))
BOOK_PATH = os.path.join("data", "lise", "12", "biyoloji", "kitap.pdf")
RESULTS_DIR = os.path.join("tests", "evaluation", "results")

# Generator.answer() varsayilanlariyla BIREBIR AYNI (generator.py) -- eval,
# uretimin FIILEN kullandigi parametrelerle olculmeli (baska bir konfigurasyon
# olcerse sonuc uretimi TEMSIL ETMEZ).
GEN_TOP_N = 6
GEN_CANDIDATE_N = 40
RETRIEVE_TOP_K = GEN_CANDIDATE_N   # k=10 ve k=20 raporu icin >=20 yeterli; 40 rerank icin de kullanilir

# M0-6 (#38) TEKRAR-URETILEBILIRLIK -- EXP-010/EVAL-13.
# Eval, `generator.answer`in varsayilani olan temperature=0.2 ile kosuyordu ve seed
# yoktu. Olculen: ayni 27 item'in iki ardisik kosumunda 10/27 item'da URETILEN METIN
# DEGISTI, citation precision'da Δ 0.033. OPTIMIZATION.md §H'nin prompt A/B'sindeki
# "+0.008 iyilesme" iddiasi bu gurultu bandinin ALTINDA -- yani o karar
# istatistiksel olarak desteklenmiyordu.
# Uretim varsayilani (0.2) DEGISMEDI; yalniz OLCUM determinize edildi.
EVAL_TEMPERATURE = float(os.environ.get("EVAL_TEMPERATURE", "0.0"))
EVAL_SEED = int(os.environ.get("EVAL_SEED", "20260911"))


def _git_sha(short: bool = True) -> str | None:
    """M0-8 (#40): olcumu URETEN kod surumu. Sonuc dosyalarinda bu yoktu ->
    "hangi kod bu sayiyi uretti" izlenemiyordu (EXP-010/EVAL-14).
    Kirli agac varsa sonuna '-dirty' eklenir (yayinlanmamis degisiklikle
    olculmus bir sayi ayirt edilebilsin)."""
    import subprocess
    try:
        args = ["git", "rev-parse", "--short" if short else "HEAD", "HEAD"]
        sha = subprocess.run([a for a in args if a != "HEAD" or True][:3] if short
                             else ["git", "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        if not sha:
            return None
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                               text=True, timeout=10).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return None


def _seed_everything(seed: int = EVAL_SEED) -> dict:
    """Olcumu tekrar-uretilebilir kilmak icin tum rastgelelik kaynaklarini tohumla.
    Donen dict rapor `meta`sina yazilir (hangi tohumla olculdugu izlenebilsin)."""
    import random
    random.seed(seed)
    info = {"seed": seed, "numpy": False, "torch": False, "torch_deterministic": False}
    try:
        import numpy as np
        np.random.seed(seed)
        info["numpy"] = True
    except Exception:
        pass
    try:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        info["torch"] = True
        # DURUST SINIR: cuDNN/cuBLAS determinizmi bazi cekirdeklerde saglanamaz;
        # istek "warn_only" ile -- saglanamayan yerde SESSIZ kalmaz, uyarir.
        try:
            torch.use_deterministic_algorithms(True, warn_only=True)
            info["torch_deterministic"] = True
        except Exception:
            pass
    except Exception:
        pass
    return info


def _load_dotenv(path: str = ".env") -> None:
    """.env'deki KEY=VALUE satirlarini os.environ'a yukler (uzerine YAZMAZ).
    DEGERLER ASLA stdout/log'a yazilmaz (gorev kosulu)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def _retry(fn, *, attempts: int = 2, label: str = ""):
    """Gorev kosulu: 'transient segfault (qdrant/CUDA) olursa 1 kez retry'.
    DURUST SINIR: gercek bir OS-seviyeli segfault Python islemini oldurur,
    ayni islem icinden yakalanip retry EDILEMEZ (bunun icin disaridan bir
    supervisor/process gerekir -- bu projede yok). Burada yakalanabilen
    TUM Exception'lar (RuntimeError/qdrant/CUDA OOM dahil) icin 1 kez daha
    denenir; ikinci deneme de patlarsa hata YUKSELTILIR (sessizce yutulmaz)."""
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            print(f"[eval] {label} basarisiz (deneme {i + 1}/{attempts}): "
                 f"{type(e).__name__}: {e}", file=sys.stderr)
    raise last_exc


def load_golden(path: str = GOLDEN_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_pipeline(book_path: str = BOOK_PATH) -> dict:
    """TAM pipeline'i BIR KEZ kurar (agir: PDF parse + embed + index + rerank
    model yukleme). Donen dict runner'in geri kalaninda kullanilir."""
    t0 = time.time()
    doc = _retry(lambda: build_canonical(book_path, sinif="12", ders="biyoloji"),
                label="build_canonical")
    chunks = chunk_document(doc)
    children = [c for c in chunks if c.level == "child"]
    # M0-7 (#39) -- EXP-010/ACC-10: eskiden burada KOSULSUZ child+parent vardi,
    # `service/http_app.py` ise yalniz child koyuyordu -> parent genisletme eval'de
    # ACIK, uretimde KAPALI. Yani yayinlanmis 0.645/0.883 uretimi temsil etmiyordu.
    # Artik iki yol AYNI anahtari (`RAG_INCLUDE_PARENTS`) okur.
    # DURUSTLUK NOTU: varsayilan uretimin bugunku davranisina (KAPALI) hizalandi;
    # bu, gecmis kosumlarla (parent ACIK) kiyaslanabilirligi BOZAR. Eski davranisi
    # yeniden uretmek icin RAG_INCLUDE_PARENTS=1. Hangisinin dogru oldugu #39'un
    # A/B'siyle karara baglanacak.
    from ..service.http_app import INCLUDE_PARENTS_DEFAULT
    include_parents = INCLUDE_PARENTS_DEFAULT
    chunks_by_id = ({c.chunk_id: c for c in chunks} if include_parents
                    else {c.chunk_id: c for c in children})
    span_meta = build_span_meta(doc)
    print(f"[eval] canonical+chunk: {len(doc.units)} birim, {len(children)} child chunk "
         f"({time.time() - t0:.1f}s)")

    emb = BGEM3Embedder()
    ids, vecs = _retry(lambda: emb.embed_chunks(children, batch_size=16), label="embed_chunks")
    texts = [c.text for c in children]
    sparse_docs = _retry(lambda: emb.embed_sparse(texts, batch_size=16), label="embed_sparse")
    dense = DenseIndex(dim=1024).build(ids, vecs)
    bm25 = BM25Index().build(ids, texts)
    sparse = SparseIndex().build(ids, sparse_docs)
    retriever = HybridRetriever(emb, dense, bm25, sparse)
    print(f"[eval] embed+index hazir ({time.time() - t0:.1f}s toplam)")

    reranker = BGEReranker()
    _retry(lambda: reranker.rerank("isinma", [("x", "deneme metni")]), label="reranker_warmup")

    deepseek = DeepSeek()
    # LLM güvenlik sınıflandırıcı (2. katman) — regex'in kaçırdığı parafraz/dolaylı
    # zararlıyı yakalar (baseline: zararlı 1/3). Eval ürünün TAM guardlı hâlini ölçer.
    from ..guard import LLMSafetyClassifier
    from ..memory import HistoryAwareRewriter
    generator = Generator(retriever, reranker, chunks_by_id, span_meta, deepseek,
                          ders="biyoloji", abstain_score=0.30, module="eval",
                          safety_classifier=LLMSafetyClassifier(deepseek, module="eval"),
                          context_packing=True,   # token bütçesi + lost-in-the-middle
                          rewriter=HistoryAwareRewriter(deepseek, module="eval"))  # çok-turlu
    print(f"[eval] pipeline tamamen hazir ({time.time() - t0:.1f}s toplam)")
    return dict(doc=doc, chunks_by_id=chunks_by_id, span_meta=span_meta,
               retriever=retriever, reranker=reranker, generator=generator,
               children=children, include_parents=include_parents)


def _ranked_sets_for_hits(hits, chunks_by_id) -> tuple[list[set], list[set]]:
    span_sets, page_sets = [], []
    for cid, _score in hits:
        ch = chunks_by_id.get(cid)
        if ch is None:
            span_sets.append(set())
            page_sets.append(set())
            continue
        span_sets.append(set(ch.span_ids))
        page_sets.append(M.page_range_set(ch.page_start, ch.page_end))
    return span_sets, page_sets


# M0-5 (#37) HAKEM ORNEKLEMI -- EXP-010/EVAL-04.
# Eski kural "critical + temsil edilmeyen unitede ilk item" idi. Olculen sonuc:
# bio v1.1'de judge yalniz 22/133 cevaplanabilir item (%16.5) aliyordu ve
# ornegin kategori dagilimi `zor` 12 + `multi_turn` 10 idi -- yani `kolay` (46)
# ve `orta` (53) item'larin TAMAMI hakemsizdi. Kullanicilarin en sik soracagi
# soru sinifinda uretim kalitesi HIC olculmemisti. Ayrica kimya/fizik setlerinde
# `critical & cevapla` item olmadigi icin judge n=0 kaliyordu -> EXP-005/008'in
# non-bio "kalite" iddiasinda faithfulness/correctness hic olculmemisti.
#
# Yeni kural: critical'lar ZORUNLU cekirdek + kalan kota (kategori x senaryo)
# tabakalarina ORANTILI, sabit tohumla rastgele dagitilir. Her tabaka ve her
# unite en az 1 ornekle temsil edilir. Tohum sabit -> ayni set ayni ornegi verir.
JUDGE_SAMPLE_N = int(os.environ.get("JUDGE_SAMPLE_N", "40"))
JUDGE_IDS_PATH = os.environ.get("JUDGE_IDS_PATH")     # dondurulmus kume (surum kiyasi)


def _judge_stratum(it: dict) -> tuple:
    """Tabaka anahtari: (kategori, senaryo). Ikisi de golden set ALANI -- id'ye
    bagli degil, set degisirse yine calisir."""
    return (it.get("kategori") or "?", it.get("senaryo") or "-")


def _select_judge_ids(items: list[dict], sample_n: int | None = None,
                      seed: int | None = None) -> set[str]:
    """Tabakali rastgele hakem ornegi (sabit tohum).

    1) `beklenen_davranis == 'cevapla'` VE `critical` olan HER item (zorunlu).
    2) Her (kategori, senaryo) tabakasindan ve her uniteden en az 1 item.
    3) Kalan kota, tabaka buyuklugune ORANTILI olarak rastgele dagitilir.

    `JUDGE_IDS_PATH` verilmisse kume DOSYADAN okunur (dondurulmus judge kumesi --
    iki kosumu ayni ornek uzerinde karsilastirmak icin; EVAL-04'un "farkli
    ornekler arasi kiyas" sorununu kapatir)."""
    if JUDGE_IDS_PATH and os.path.exists(JUDGE_IDS_PATH):
        with open(JUDGE_IDS_PATH, encoding="utf-8") as fh:
            frozen = set(json.load(fh))
        valid = {it["id"] for it in items}
        missing = frozen - valid
        if missing:
            print(f"[eval] UYARI: dondurulmus judge kumesindeki {len(missing)} id "
                 f"bu golden set'te YOK: {sorted(missing)[:5]}...", file=sys.stderr)
        return frozen & valid

    import random
    sample_n = JUDGE_SAMPLE_N if sample_n is None else sample_n
    rnd = random.Random(EVAL_SEED if seed is None else seed)

    pool = [it for it in items if it["beklenen_davranis"] == "cevapla"]
    ids = {it["id"] for it in pool if it.get("critical")}

    strata: dict[tuple, list[dict]] = {}
    for it in pool:
        strata.setdefault(_judge_stratum(it), []).append(it)
    for key in strata:
        strata[key].sort(key=lambda x: x["id"])        # deterministik taban

    # (2) her tabakadan en az 1
    for key, bucket in sorted(strata.items()):
        if any(it["id"] in ids for it in bucket):
            continue
        ids.add(rnd.choice(bucket)["id"])

    # (2b) her unite en az 1 (eski kural korunur)
    seen_units = {it.get("unite") for it in pool if it["id"] in ids}
    for it in sorted(pool, key=lambda x: x["id"]):
        u = it.get("unite")
        if u and u not in seen_units:
            ids.add(it["id"])
            seen_units.add(u)

    # (3) kalan kotayi tabaka buyuklugune orantili dagit
    remaining = sample_n - len(ids)
    if remaining > 0:
        total = sum(len(b) for b in strata.values()) or 1
        base_remaining = remaining
        for key, bucket in sorted(strata.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            if remaining <= 0:
                break
            quota = max(1, round(base_remaining * len(bucket) / total))
            free = [it["id"] for it in bucket if it["id"] not in ids]
            rnd.shuffle(free)
            take = free[:min(quota, remaining, len(free))]
            ids.update(take)
            remaining -= len(take)
        # DOLDURMA TURU: orantili dagitim yuvarlama yuzunden hedefin ALTINDA
        # kalabilir. Hedef ornekleme buyuklugu istatistiksel gucu belirledigi
        # icin (bkz. #33 CI) eksik bırakmak metrigi zayiflatir -> kalan bos
        # id'lerden deterministik olarak tamamla.
        if remaining > 0:
            leftovers = sorted(it["id"] for it in pool if it["id"] not in ids)
            rnd.shuffle(leftovers)
            ids.update(leftovers[:remaining])
    return ids


def _judge_composition(items: list[dict], judge_ids: set[str]) -> dict:
    """Hakem orneginin BILESIMI + kapsami -- rapora yazilir ki "0.988" sayisinin
    hangi item sinifindan geldigi gorunsun (EVAL-04'un korlugu tam buydu)."""
    pool = [it for it in items if it["beklenen_davranis"] == "cevapla"]
    sel = [it for it in pool if it["id"] in judge_ids]
    by_cat: dict[str, int] = {}
    by_stratum: dict[str, int] = {}
    for it in sel:
        by_cat[it.get("kategori") or "?"] = by_cat.get(it.get("kategori") or "?", 0) + 1
        k = "|".join(_judge_stratum(it))
        by_stratum[k] = by_stratum.get(k, 0) + 1
    uncovered = sorted({(it.get("kategori") or "?") for it in pool}
                       - set(by_cat)) or []
    return {"n_selected": len(sel), "n_answerable": len(pool),
            "coverage": (len(sel) / len(pool)) if pool else None,
            "by_kategori": by_cat, "by_stratum": by_stratum,
            "kategoriler_hakemsiz": uncovered,
            "sample_n_target": JUDGE_SAMPLE_N,
            "frozen_from": JUDGE_IDS_PATH if JUDGE_IDS_PATH else None}


# ---------------------------------------------------------------------------
# M0-4 (#36) — UC OLCUM MODU (RES-003 §8 "3 testi ayir")
#
# Tek modla kosmak "hata parser/retriever'da mi generator'da mi?" sorusunu
# cevaplanamaz kiliyordu (EXP-010/EVAL-09): olculen citation precision 0.645 ve
# correctness 0.838 sayilarinda hangisinin payi oldugu bilinmiyordu.
#
#   retrieval_only  : LLM HIC cagrilmaz. Ucuz, deterministik, CI'da kosabilir.
#                     Yalniz "gold kanit getirildi mi" sorusunu olcer.
#   oracle_context  : Baglam = GOLD span'lari tasiyan chunk'lar. "Retrieval
#                     kusursuz olsaydi uretim ne kadar iyi olurdu" UST SINIRI.
#                     Uretim yolu (prompt/guard/atif eslemesi/cekimserlik)
#                     BIREBIR ayni -- yalniz retriever+reranker stub'lanir, boylece
#                     urun kodu degismez.
#   end_to_end      : gercek boru hatti (onceki tek davranis).
#
# Rapora `hata_atfi = e2e - oracle` yazilir: fark generator'in degil retrieval'in
# payidir.
#
# DURUST SINIR: oracle modunda parent genisletme DEVRE DISI (stub chunk'larda
# parent_id=None) -- bu bilincli. (a) parent genisletme bir RETRIEVAL kararidir,
# uretim kalitesini izole ederken karistirmamak gerekir; (b) ACC-03 gosterdi ki
# parent metni atifi yanlis sayfaya kaydiriyor, oracle olcumu bu gurultuyu
# tasimamali. Yani oracle sayilari "saf yaprak span" kosuludur.
# ---------------------------------------------------------------------------
EVAL_MODES = ("retrieval_only", "oracle_context", "end_to_end")


class _OracleRetriever:
    """Gercek retrieval yerine GOLD chunk'lari dondurur (skor 1.0).

    Skorun 1.0 olmasi bilincli: oracle kosulunda kanit TANIMI GEREGI yeterli,
    bu yuzden `abstain_score` fail-closed esigi tetiklenmemeli. Eger model yine
    de cekimser kalirsa bu GENERATOR'IN karari olur -- olcmek istedigimiz de bu."""

    def __init__(self, chunk_ids: list[str]):
        self._ids = list(chunk_ids)

    def retrieve(self, query, top_k: int = 20, **kwargs):
        return [(cid, 1.0) for cid in self._ids[:top_k]]


class _OracleReranker:
    """Verilen sirayi korur, skoru 1.0 verir (siralama oracle'da anlamsiz)."""

    def rerank(self, query, pairs):
        return [(cid, 1.0) for cid, _text in pairs]


def _oracle_chunk_ids(gold_spans: set, chunks_by_id: dict) -> list[str]:
    """Gold span tasiyan CHILD chunk'lar, sayfa sirasinda (deterministik)."""
    hits = [(ch.page_start, cid) for cid, ch in chunks_by_id.items()
            if ch.level == "child" and set(ch.span_ids) & gold_spans]
    return [cid for _page, cid in sorted(hits)]


def _oracle_generator(pipeline: dict, gold_spans: set):
    """Uretim Generator'inin AYNI ayarlariyla, yalniz retriever+reranker stub'li
    bir kopyasini kurar. Urun kodu degismez; prompt/guard/atif yolu birebir ayni.
    Parent genisletme dogal olarak devre disi kalir (stub chunks_by_id'de
    parent_id=None) -- bkz. yukaridaki DURUST SINIR notu."""
    import dataclasses

    base = pipeline["generator"]
    ids = _oracle_chunk_ids(gold_spans, pipeline["chunks_by_id"])
    stub_chunks = {}
    for cid in ids:
        ch = pipeline["chunks_by_id"][cid]
        stub_chunks[cid] = dataclasses.replace(ch, parent_id=None)
    gen = Generator(_OracleRetriever(ids), _OracleReranker(), stub_chunks,
                    pipeline["span_meta"], base.deepseek,
                    ders=base.ders, abstain_score=base.abstain_score,
                    module="eval-oracle", safety_classifier=base.safety_classifier,
                    context_packing=base.context_packing,
                    context_max_tokens=base.context_max_tokens,
                    rewriter=base.rewriter)
    return gen, ids


def _eval_item(item: dict, pipeline: dict, judge: LlmJudge | None,
              judge_ids: set[str], mode: str = "end_to_end") -> dict:
    if mode not in EVAL_MODES:
        raise ValueError(f"bilinmeyen mod {mode!r}; secenekler: {EVAL_MODES}")
    item_id = item["id"]
    query = item["soru"]
    gold_spans = set(item.get("gold_kaynak_spanlar") or [])
    gold_pages = set(item.get("gold_sayfalar") or [])
    chunks_by_id = pipeline["chunks_by_id"]
    generator = pipeline["generator"]

    retr_metrics = M.RetrievalMetrics()
    retr_post_metrics = M.RetrievalMetrics()
    contexts_for_judge = []
    if gold_spans:
        hits = _retry(lambda: pipeline["retriever"].retrieve(query, top_k=RETRIEVE_TOP_K),
                     label=f"retrieve[{item_id}]")
        span_sets, page_sets = _ranked_sets_for_hits(hits, chunks_by_id)
        retr_metrics = M.compute_retrieval_metrics(span_sets, page_sets, gold_spans, gold_pages)
        # M0-3 (#35): rerank ARTIK HER item'da olculur. Eskiden yalniz
        # `item_id in judge_ids` ise cagriliyordu -> 200 item'in 178'inde
        # reranker'in etkisi hic olculmuyordu ve benchmark.md §5'in zorunlu
        # ablation'i ("her bilesen kanitla girer") acik kaliyordu.
        contexts_for_judge = _retry(
            lambda: rerank_select(query, hits, chunks_by_id, pipeline["reranker"],
                                  top_n=GEN_TOP_N, candidate_n=GEN_CANDIDATE_N),
            label=f"rerank_select[{item_id}]")
        post_span_sets = [set(c.span_ids) for c in contexts_for_judge]
        post_page_sets = [M.page_range_set(chunks_by_id[c.chunk_id].page_start,
                                           chunks_by_id[c.chunk_id].page_end)
                          if c.chunk_id in chunks_by_id else set()
                          for c in contexts_for_judge]
        retr_post_metrics = M.compute_retrieval_metrics(
            post_span_sets, post_page_sets, gold_spans, gold_pages)

    # retrieval_only: LLM HIC cagrilmaz -> ucuz, deterministik, CI'da kosabilir.
    if mode == "retrieval_only":
        return {
            "id": item_id, "mode": mode, "kategori": item["kategori"],
            "unite": item.get("unite"), "kazanim_kod": item.get("kazanim_kod"),
            "critical": bool(item.get("critical")),
            "beklenen_davranis": item["beklenen_davranis"],
            "zararli_kategori": item.get("zararli_kategori"), "soru": query,
            "retrieval": vars(retr_metrics),
            "retrieval_post_rerank": vars(retr_post_metrics),
            "citation": vars(M.CitationMetrics()),
            "guardrail": {"passed": None, "fail_closed": None,
                          "abstained": None, "reason": "retrieval_only"},
            "generation": {"text": "", "abstained": None, "reason": "retrieval_only",
                           "n_citations": 0, "invalid_citations": [],
                           "cost_usd": 0.0, "latency_s": 0.0},
            "judge": None,
        }

    oracle_ids = None
    if mode == "oracle_context":
        if not gold_spans:
            # gold'u olmayan item (kapsam-disi/zararli/belirsiz) oracle'da
            # ANLAMSIZ -- atlanir, sayilara karismaz (0.0 ile karistirilmaz).
            return {"id": item_id, "mode": mode, "kategori": item["kategori"],
                    "beklenen_davranis": item["beklenen_davranis"],
                    "skipped": "oracle_context: gold span yok", "soru": query,
                    "retrieval": vars(retr_metrics),
                    "retrieval_post_rerank": vars(retr_post_metrics),
                    "citation": vars(M.CitationMetrics()),
                    "guardrail": {"passed": None, "fail_closed": None,
                                  "abstained": None, "reason": "oracle_skipped"},
                    "generation": {"text": "", "abstained": None,
                                   "reason": "oracle_skipped", "n_citations": 0,
                                   "invalid_citations": [], "cost_usd": 0.0,
                                   "latency_s": 0.0},
                    "judge": None}
        generator, oracle_ids = _oracle_generator(pipeline, gold_spans)

    t0 = time.time()
    # multi_turn item'larda konuşma geçmişini ver → history-aware rewrite devreye
    # girer (bkz. src/memory). Diğer item'larda history=None (davranış değişmez).
    history = item.get("konusma_gecmisi")
    result = _retry(lambda: generator.answer(query, history=history,
                                             top_n=GEN_TOP_N, candidate_n=GEN_CANDIDATE_N,
                                             temperature=EVAL_TEMPERATURE),
                    label=f"generator.answer[{item_id}]")
    gen_latency = time.time() - t0

    cited_spans: set = set()
    cited_pages: set = set()
    for c in result.citations:
        cited_spans |= set(c.get("span_ids") or [])
        cited_pages |= set(c.get("pages") or [])
    citation_m = M.citation_precision_recall(cited_spans, gold_spans,
                                             cited_pages=cited_pages, gold_pages=gold_pages)

    guardrail_passed = M.guardrail_pass(item["beklenen_davranis"], result.abstained, result.reason)
    fail_closed = M.is_fail_closed(result.abstained, result.cost_usd)

    judge_result = None
    if judge is not None and item_id in judge_ids and item["beklenen_davranis"] == "cevapla":
        if result.abstained:
            judge_result = {"skipped": True,
                           "reason": f"cevap abstain oldu (reason={result.reason}) -- "
                                     f"judge'a gonderilmedi (uretilmis metin yok)"}
        else:
            retrieved_texts = [_source_text_with_parent(ctx) for ctx in contexts_for_judge]
            jres = judge.evaluate(question=query, answer_text=result.text,
                                  retrieved_contexts=retrieved_texts,
                                  gold_answer=item.get("gold_cevap"))
            costlog.record(module="eval", model=jres.model, usage=jres.usage, items=1,
                           config={"metric": "faithfulness+answer_relevancy+answer_correctness",
                                   "method": JUDGE_METHOD, "item_id": item_id},
                           note=f"llm-judge {item_id}: faith={jres.faithfulness} "
                                f"rel={jres.answer_relevancy} corr={jres.answer_correctness}")
            judge_result = {
                "faithfulness": jres.faithfulness, "faithfulness_reason": jres.faithfulness_reason,
                "answer_relevancy": jres.answer_relevancy,
                "answer_relevancy_reason": jres.answer_relevancy_reason,
                "answer_correctness": jres.answer_correctness,
                "answer_correctness_reason": jres.answer_correctness_reason,
                "cost_usd": jres.cost_usd, "model": jres.model, "errors": jres.errors,
            }

    return {
        "id": item_id, "mode": mode,
        "kategori": item["kategori"], "unite": item.get("unite"),
        "kazanim_kod": item.get("kazanim_kod"), "critical": bool(item.get("critical")),
        "beklenen_davranis": item["beklenen_davranis"],
        "zararli_kategori": item.get("zararli_kategori"),
        "soru": query,
        "n_oracle_chunks": (len(oracle_ids) if oracle_ids is not None else None),
        "retrieval": vars(retr_metrics),
        "retrieval_post_rerank": vars(retr_post_metrics),
        "citation": vars(citation_m),
        "guardrail": {"passed": guardrail_passed, "fail_closed": fail_closed,
                     "abstained": result.abstained, "reason": result.reason},
        "generation": {"text": result.text, "abstained": result.abstained,
                       "reason": result.reason, "n_citations": len(result.citations),
                       "invalid_citations": result.invalid_citations,
                       "cost_usd": result.cost_usd, "latency_s": gen_latency},
        "judge": judge_result,
    }


def _failed_item(item: dict, exc: Exception) -> dict:
    """AUDIT EXP-007 #29/eval#4: bir golden item değerlendirilirken hata olursa
    (eksik alan, pipeline hatası) TÜM run'ı düşürme — hatayı bu item'a kaydet,
    aggregate ile uyumlu boş-metrik iskeleti dön, döngü devam etsin."""
    return {
        "id": item.get("id", "?"), "kategori": item.get("kategori", "?"),
        "unite": item.get("unite"), "kazanim_kod": item.get("kazanim_kod"),
        "critical": bool(item.get("critical")),
        "beklenen_davranis": item.get("beklenen_davranis", "?"),
        "zararli_kategori": item.get("zararli_kategori"),
        "soru": item.get("soru", ""),
        "retrieval": {}, "citation": {},
        "guardrail": {"passed": None, "fail_closed": None, "abstained": None, "reason": "eval_error"},
        "generation": {"text": "", "abstained": None,
                       "reason": f"eval_error: {type(exc).__name__}", "n_citations": 0,
                       "invalid_citations": [], "cost_usd": 0.0, "latency_s": 0.0},
        "judge": None,
        "error": f"{type(exc).__name__}: {exc}",
    }


# --------------------------------------------------------------------------
# Aggregate + rapor
# --------------------------------------------------------------------------

# @5 + nDCG + all_evidence: OPTIMIZATION.md §H STANDING KARAR'in birincil metrikleri
# (recall@5/@10 + MRR); @20 yalniz UST SINIR gostergesi -- doygun (EXP-010/EVAL-08).
_RETRIEVAL_KEYS = ["recall_at_5", "recall_at_10", "recall_at_20",
                  "precision_at_5", "precision_at_10", "precision_at_20",
                  "mrr_value", "ndcg_at_10",
                  "all_evidence_recall_at_10", "all_evidence_recall_at_20",
                  "page_recall_at_5", "page_recall_at_10", "page_recall_at_20",
                  "page_precision_at_10", "page_precision_at_20", "page_mrr_value",
                  "page_ndcg_at_10"]
_CITATION_KEYS = ["precision", "recall", "precision_page", "recall_page"]
_JUDGE_KEYS = ["faithfulness", "answer_relevancy", "answer_correctness"]


def _aggregate(subset: list[dict]) -> dict:
    n = len(subset)
    retrieval = {k: M.mean([it["retrieval"].get(k) for it in subset]) for k in _RETRIEVAL_KEYS}
    citation = {k: M.mean([it["citation"].get(k) for it in subset]) for k in _CITATION_KEYS}
    guardrail_vals = [it["guardrail"]["passed"] for it in subset if it["guardrail"]["passed"] is not None]
    guardrail_pass_rate = (sum(1 for v in guardrail_vals if v) / len(guardrail_vals)
                          if guardrail_vals else None)
    fc_vals = [it["guardrail"]["fail_closed"] for it in subset if it["guardrail"]["fail_closed"] is not None]
    fail_closed_rate = sum(1 for v in fc_vals if v) / len(fc_vals) if fc_vals else None
    judged = [it["judge"] for it in subset if it["judge"] and not it["judge"].get("skipped")]
    skipped = [it["judge"] for it in subset if it["judge"] and it["judge"].get("skipped")]
    judge_agg = {k: M.mean([j.get(k) for j in judged]) for k in _JUDGE_KEYS}
    judge_agg["n_judged"] = len(judged)
    # M0-2 (#34) SURVIVORSHIP BIAS -- EXP-010/EVAL-05.
    # Cekimser kalan bir `cevapla` item'i "uretilmis metin yok" diye judge'a
    # gonderilmiyor ve YUKARIDAKI paydadan da dusuyordu. Ama "cevap uretemedi"
    # EN CIDDI kalite hatasidir: v1.1 kosumunda bio12-v1-mt008 hem yanlis-abstain
    # listesindeydi hem faithfulness'tan silinmisti; dogru sayilsa 0.988 -> 0.942.
    # Yani abstain orani arttikca faithfulness YUKSELIYORDU (ters tesvik).
    # Cozum: iki sayiyi AYRI raporla, ikisi birlikte yazilmadan sonuc yazilmaz.
    #   *_answered   -> yalniz uretilen cevaplar (eski davranis, kiyaslanabilirlik)
    #   *_penalized  -> cekimser item 0.0 sayilir (durust ust-sinir olmayan sayi)
    n_pen = len(judged) + len(skipped)
    for k in _JUDGE_KEYS:
        judge_agg[k + "_answered"] = judge_agg[k]
        vals = [j.get(k) for j in judged if j.get(k) is not None] + [0.0] * len(skipped)
        judge_agg[k + "_penalized"] = (sum(vals) / len(vals)) if vals else None
    judge_agg["n_judge_skipped_abstained"] = len(skipped)
    judge_agg["n_judge_selected"] = n_pen
    # `cevapla` beklenen item'larda cevap URETME orani (birincil metrik, hedef >=0.98).
    # Bu, yukaridaki penalized sayilarinin okunmasi icin gereken baglami verir.
    answerable = [it for it in subset if it.get("beklenen_davranis") == "cevapla"]
    answered = [it for it in answerable
                if not (it.get("guardrail") or {}).get("abstained", False)]
    judge_agg["answerable_coverage"] = (len(answered) / len(answerable)
                                        if answerable else None)
    judge_agg["n_answerable"] = len(answerable)
    # AUDIT EXP-007 #29/eval#6: mean() None'ları düşürür → "faithfulness (n=N)" ama
    # ortalama gerçekte < N item üzerinden olabilir (judge hatası → skor None ama
    # skipped değil → judged'da kalır). Her metrik için KATKI VEREN (None-olmayan)
    # sayıyı + hakem-hata sayısını AYRI raporla (survivorship pass-bias görünür olsun).
    for k in _JUDGE_KEYS:
        judge_agg[k + "_n"] = sum(1 for j in judged if j.get(k) is not None)
    judge_agg["n_errors"] = sum(1 for j in judged if j.get("errors"))
    return {"n": n, "retrieval": retrieval, "citation": citation,
           "guardrail_pass_rate": guardrail_pass_rate, "n_guardrail_applicable": len(guardrail_vals),
           "fail_closed_rate": fail_closed_rate, "n_abstained": len(fc_vals),
           "n_errors": sum(1 for it in subset if it.get("error")),
           "judge": judge_agg}


def _weakness_score(it: dict) -> float:
    """Siralama icin TEK bir kompozit skor (dusuk = zayif). Guardrail
    UYGULANABILIR bir item'da BASARISIZSA sifir (en kotu) -- guvenlik/kapsam
    hatasi her zaman en kritik zayifliktir. Aksi halde mevcut (None olmayan)
    kalite sinyallerinin ortalamasi (retrieval recall@20, citation recall,
    faithfulness, answer_correctness)."""
    if it.get("error"):                 # #29: değerlendirilemeyen item en zayıf (görünür kalsın)
        return 0.0
    g = it["guardrail"]["passed"]
    if g is False:
        return 0.0
    candidates = [it["retrieval"].get("recall_at_20"), it["citation"].get("recall")]
    if it["judge"] and not it["judge"].get("skipped"):
        candidates += [it["judge"].get("faithfulness"), it["judge"].get("answer_correctness")]
    vals = [v for v in candidates if v is not None]
    if not vals:
        return 1.0 if g is not False else 0.5   # olcum yok -> notr (siralamada ortada)
    return sum(vals) / len(vals)


def _fmt(x) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, bool):
        return "evet" if x else "hayir"
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def _md_report(golden: dict, items_out: list[dict], overall: dict, by_category: dict,
              total_cost_usd: float, judge_method: str, judge_ids: set[str],
              elapsed_s: float, mode: str = "end_to_end",
              golden_path: str = "?") -> str:
    lines = []
    # M0-8 (#40): baslik sabit "golden_12bio_v0" diyordu; hangi set/mod/kod
    # surumuyle olculdugu artik basliktan okunuyor.
    lines.append(f"# Eval Raporu — {os.path.basename(golden_path)} "
                 f"({golden.get('version')}) · mod={mode} · kod={_git_sha() or '?'} "
                 f"· temperature={EVAL_TEMPERATURE} — TASLAK olcum")
    lines.append("")
    lines.append("**DURUM: bu TASLAK golden set'e karsi HAM olcumdur. Kendini 'basarili' "
                "ilan ETMEZ; yorum Kadir/evaluator'a aittir (bkz. tests/golden/README.md "
                "benchmark kilidi).**")
    lines.append("")
    lines.append(f"- Calisma zamani: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC "
                f"({elapsed_s:.1f}s)")
    lines.append(f"- Item sayisi: {len(items_out)}")
    lines.append(f"- LLM-hakem yontemi: **{judge_method}** (DeepEval kutuphanesi + DeepSeek custom judge model)")
    lines.append(f"- LLM-hakem uygulanan item'lar ({len(judge_ids)}): {', '.join(sorted(judge_ids))}")
    lines.append(f"- DeepSeek maliyeti (bu eval kosusu, URETIM + HAKEM): ${total_cost_usd:.6f} "
                f"— NOT: guard LLM-siniflandirici + history-rewrite cagrilarinin maliyeti "
                f"costlog'da AYRI (module=guard/memory); bu toplam yalniz uretim+hakem'dir (#29).")
    lines.append("")

    lines.append("## Genel (tum item'lar)")
    lines.append("")
    lines.append(_aggregate_table(overall))
    lines.append("")

    lines.append("## Kategori bazinda")
    lines.append("")
    for cat, agg in by_category.items():
        lines.append(f"### {cat} (n={agg['n']})")
        lines.append("")
        lines.append(_aggregate_table(agg))
        lines.append("")

    weakest = sorted(items_out, key=_weakness_score)[:5]
    lines.append("## En dusuk skorlu 5 item (kompozit zayiflik siralamasi)")
    lines.append("")
    lines.append("| id | kategori | soru | recall@20 | citation.recall | faithfulness | correctness | guardrail.passed | not |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for it in weakest:
        note = it["generation"]["reason"] or ""
        j = it["judge"] or {}
        lines.append(
            f"| {it['id']} | {it['kategori']} | {it['soru'][:60]} "
            f"| {_fmt(it['retrieval'].get('recall_at_20'))} | {_fmt(it['citation'].get('recall'))} "
            f"| {_fmt(j.get('faithfulness'))} | {_fmt(j.get('answer_correctness'))} "
            f"| {_fmt(it['guardrail']['passed'])} | {note} |")
    lines.append("")

    lines.append("## Tum item'lar (ham)")
    lines.append("")
    lines.append("| id | kategori | beklenen | abstained | reason | recall@10 | recall@20 | "
                 "citation.P | citation.R | guardrail.passed | fail_closed |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for it in items_out:
        lines.append(
            f"| {it['id']} | {it['kategori']} | {it['beklenen_davranis']} "
            f"| {_fmt(it['generation']['abstained'])} | {it['generation']['reason']} "
            f"| {_fmt(it['retrieval'].get('recall_at_10'))} | {_fmt(it['retrieval'].get('recall_at_20'))} "
            f"| {_fmt(it['citation'].get('precision'))} | {_fmt(it['citation'].get('recall'))} "
            f"| {_fmt(it['guardrail']['passed'])} | {_fmt(it['guardrail']['fail_closed'])} |")
    lines.append("")
    return "\n".join(lines)


def _aggregate_table(agg: dict) -> str:
    r = agg["retrieval"]
    c = agg["citation"]
    j = agg["judge"]
    lines = ["| Metrik | Deger |", "|---|---|"]
    lines.append(f"| n | {agg['n']} |")
    lines.append(f"| recall@10 (span) | {_fmt(r.get('recall_at_10'))} |")
    lines.append(f"| recall@20 (span) — yalniz UST SINIR gostergesi, doygun | {_fmt(r.get('recall_at_20'))} |")
    lines.append(f"| precision@10 (span) | {_fmt(r.get('precision_at_10'))} |")
    lines.append(f"| precision@20 (span) | {_fmt(r.get('precision_at_20'))} |")
    lines.append(f"| MRR (span) — **birincil** | {_fmt(r.get('mrr_value'))} |")
    lines.append(f"| nDCG@10 (span) — siralama kalitesi | {_fmt(r.get('ndcg_at_10'))} |")
    lines.append(f"| all-evidence recall@10 (span, kismi kredi YOK) | {_fmt(r.get('all_evidence_recall_at_10'))} |")
    lines.append(f"| all-evidence recall@20 (span, kismi kredi YOK) | {_fmt(r.get('all_evidence_recall_at_20'))} |")
    lines.append(f"| recall@5 (sayfa) | {_fmt(r.get('page_recall_at_5'))} |")
    lines.append(f"| recall@10 (sayfa) | {_fmt(r.get('page_recall_at_10'))} |")
    lines.append(f"| recall@20 (sayfa) | {_fmt(r.get('page_recall_at_20'))} |")
    lines.append(f"| citation precision | {_fmt(c.get('precision'))} |")
    lines.append(f"| citation recall | {_fmt(c.get('recall'))} |")
    lines.append(f"| guardrail pass-rate (n={agg['n_guardrail_applicable']}) | {_fmt(agg['guardrail_pass_rate'])} |")
    lines.append(f"| fail-closed orani (n={agg['n_abstained']} abstain) | {_fmt(agg['fail_closed_rate'])} |")
    # M0-2 (#34): cevap URETME orani. Asagidaki *_penalized sayilari ancak bu
    # baglamla okunabilir -- abstain orani arttikca *_answered YUKSELIR (ters tesvik).
    if j.get("answerable_coverage") is not None:
        lines.append(f"| **answerable coverage** (n={j.get('n_answerable')} `cevapla` item) "
                     f"| {_fmt(j.get('answerable_coverage'))} |")
    # per-metrik n = ortalamaya KATKI VEREN item (hakem hatası olanlar hariç, #29)
    # İKİ BİÇİM ZORUNLU (#34): _answered (üretilen cevaplar) + _penalized (çekimser=0.0).
    for key, label in (("faithfulness", "faithfulness"),
                       ("answer_relevancy", "answer_relevancy"),
                       ("answer_correctness", "answer_correctness")):
        n_ans = j.get(key + "_n", j["n_judged"])
        lines.append(f"| {label} — answered (n={n_ans}) | {_fmt(j.get(key + '_answered', j.get(key)))} |")
        lines.append(f"| {label} — **penalized** (cekimser=0.0, n={j.get('n_judge_selected')}) "
                     f"| {_fmt(j.get(key + '_penalized'))} |")
    if j.get("n_judge_skipped_abstained"):
        lines.append(f"| ⚠ cekimser kaldigi icin hakemsiz item | "
                     f"{j['n_judge_skipped_abstained']} (penalized'da 0.0 sayildi) |")
    if j.get("n_errors"):
        lines.append(f"| ⚠ hakem-hatası item | {j['n_errors']} (skor None → ortalamaya girmedi) |")
    if agg.get("n_errors"):
        lines.append(f"| ⚠ değerlendirilemeyen item (eval_error) | {agg['n_errors']} |")
    return "\n".join(lines)


def run(golden_path: str = GOLDEN_PATH, book_path: str = BOOK_PATH,
       results_dir: str = RESULTS_DIR, mode: str = "end_to_end") -> dict:
    """M0-4 (#36): `mode` ile uc olcum -- bkz. EVAL_MODES ve yukarisindaki not.
    `retrieval_only` LLM cagirmaz, bu yuzden API anahtari da GEREKMEZ (CI'da kosar)."""
    if mode not in EVAL_MODES:
        raise ValueError(f"bilinmeyen mod {mode!r}; secenekler: {EVAL_MODES}")
    _load_dotenv()
    # Anahtar kontrolu saglayici-bagimsiz olmali (EXP-009): uretici artik
    # LLM_BASE_URL/LLM_MODEL ile baska bir OpenAI-uyumlu uca alinabiliyor, o
    # durumda DEEPSEEK_API_KEY hic ayarli olmayabilir. Kaynak: providers.deepseek.
    from ..providers.deepseek import _KEY_ENV_NAMES, _env
    if mode != "retrieval_only" and not any(_env(n) for n in _KEY_ENV_NAMES):
        raise RuntimeError(
            "API anahtari yok (.env kontrol et): "
            + " / ".join(_KEY_ENV_NAMES)
            + " -- gercek eval kosusu icin gerekli.")
    if not os.path.exists(book_path):
        raise FileNotFoundError(f"golden set kaynak PDF'i yok: {book_path}")

    seed_info = _seed_everything()          # M0-6 (#38): tekrar-uretilebilirlik
    t_start = time.time()
    golden = load_golden(golden_path)
    items = golden["items"]
    judge_ids = _select_judge_ids(items)
    print(f"[eval] {len(items)} item yuklendi ({golden_path}); "
         f"{len(judge_ids)} item LLM-hakem alacak: {sorted(judge_ids)}")

    pipeline = build_pipeline(book_path)
    # retrieval_only LLM cagirmaz -> hakem de kurulmaz (maliyet 0, CI-dostu).
    judge = LlmJudge() if (judge_ids and mode != "retrieval_only") else None

    items_out = []
    for i, item in enumerate(items, start=1):
        print(f"[eval] ({i}/{len(items)}) {item.get('id','?')}: {str(item.get('soru',''))[:70]!r}")
        try:
            it_out = _eval_item(item, pipeline, judge, judge_ids, mode=mode)
        except Exception as e:                       # #29: tek bozuk item run'ı düşürmesin
            print(f"       !! HATA ({type(e).__name__}: {e}) -- item atlandı, run devam")
            it_out = _failed_item(item, e)
        items_out.append(it_out)
        print(f"       -> abstained={it_out['generation']['abstained']} "
             f"reason={it_out['generation']['reason']!r} "
             f"recall@20={_fmt(it_out['retrieval'].get('recall_at_20'))} "
             f"citR={_fmt(it_out['citation'].get('recall'))}")

    overall = _aggregate(items_out)
    by_category: dict[str, dict] = {}
    for cat in sorted({it["kategori"] for it in items_out}):
        by_category[cat] = _aggregate([it for it in items_out if it["kategori"] == cat])

    total_cost_usd = sum(it["generation"]["cost_usd"] for it in items_out)
    total_cost_usd += sum((it["judge"] or {}).get("cost_usd", 0.0) for it in items_out
                         if it["judge"] and not it["judge"].get("skipped"))

    elapsed_s = time.time() - t_start
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(results_dir, exist_ok=True)
    # M0-8 (#40): dosya adi olcumu tanimlayan seyleri TASIR. Eskiden her sonuc
    # "eval_v0_*" adiyla yaziliyordu -- 200-item v1.1 kosumu bile (EVAL-14) ->
    # farkli golden surumleri/kod surumleri/modlar ayirt edilemiyordu.
    _gv = str(golden.get("version") or "vX").replace("/", "-").replace(" ", "")
    _sha = _git_sha() or "nogit"
    _stem = f"eval_{_gv}_{mode}_{_sha}_{ts}"
    json_path = os.path.join(results_dir, f"{_stem}.json")
    md_path = os.path.join(results_dir, f"{_stem}.md")

    payload = {
        "meta": {
            "golden_path": golden_path, "golden_version": golden.get("version"),
            "book_path": book_path, "generated_at_utc": ts,
            "judge_method": JUDGE_METHOD, "deepeval_available": DEEPEVAL_AVAILABLE,
            "judged_item_ids": sorted(judge_ids), "n_items": len(items_out),
            "total_cost_usd": total_cost_usd, "elapsed_s": elapsed_s,
            "gen_top_n": GEN_TOP_N, "gen_candidate_n": GEN_CANDIDATE_N,
            # M0-4 (#36) / M0-6 (#38) / M0-8 (#40): olcumu URETEN kosullar.
            # Bunlar olmadan iki sonuc dosyasi karsilastirilamaz.
            "mode": mode,
            "git_sha": _git_sha(),
            "eval_temperature": EVAL_TEMPERATURE,
            "seed": seed_info,
            "retrieve_top_k": RETRIEVE_TOP_K,
            "abstain_score": getattr(pipeline["generator"], "abstain_score", None),
            "context_packing": getattr(pipeline["generator"], "context_packing", None),
            "guard_llm": pipeline["generator"].safety_classifier is not None,
            "rewriter": pipeline["generator"].rewriter is not None,
            "llm_model": getattr(pipeline["generator"].deepseek, "model", None),
            "llm_base_url": getattr(pipeline["generator"].deepseek, "base_url", None),
            "judge_model": (getattr(judge, "model_name", None) if judge else None),
            # M0-5 (#37): "0.988" sayisinin hangi item sinifindan geldigi gorunsun
            "judge_composition": _judge_composition(items, judge_ids),
            # M0-7 (#39): parent genisletme eval ve uretimde ARTIK ayni; hangi
            # degerle olctugumuz kayda geciyor (eskiden ayrisma gizliydi).
            "include_parents": pipeline.get("include_parents"),
        },
        "overall": overall, "by_category": by_category, "items": items_out,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    md = _md_report(golden, items_out, overall, by_category, total_cost_usd,
                    JUDGE_METHOD, judge_ids, elapsed_s, mode=mode,
                    golden_path=golden_path)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n[eval] TAMAM ({elapsed_s:.1f}s). JSON: {json_path}")
    print(f"[eval] MD: {md_path}")
    print(f"[eval] DeepSeek maliyeti (uretim+hakem; guard/rewrite costlog'da ayri): ${total_cost_usd:.6f}")
    return payload


def main() -> None:
    """CLI: `python -m src.eval.runner [--mode MOD] [--golden YOL] [--book YOL]`

    M0-4 (#36) uc mod: retrieval_only (LLM'siz, ucuz, CI'da kosar) /
    oracle_context (uretim ust siniri) / end_to_end (gercek boru hatti).
    `hata_atfi = end_to_end - oracle_context` -> fark retrieval'in payidir."""
    import argparse
    ap = argparse.ArgumentParser(prog="src.eval.runner")
    ap.add_argument("--mode", default="end_to_end", choices=list(EVAL_MODES))
    ap.add_argument("--golden", default=GOLDEN_PATH)
    ap.add_argument("--book", default=BOOK_PATH)
    ap.add_argument("--results-dir", default=RESULTS_DIR)
    a = ap.parse_args()
    run(golden_path=a.golden, book_path=a.book, results_dir=a.results_dir, mode=a.mode)


if __name__ == "__main__":
    main()
