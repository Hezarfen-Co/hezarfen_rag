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

GOLDEN_PATH = os.path.join("tests", "golden", "golden_12bio_v0.json")
BOOK_PATH = os.path.join("data", "lise", "12", "biyoloji", "kitap.pdf")
RESULTS_DIR = os.path.join("tests", "evaluation", "results")

# Generator.answer() varsayilanlariyla BIREBIR AYNI (generator.py) -- eval,
# uretimin FIILEN kullandigi parametrelerle olculmeli (baska bir konfigurasyon
# olcerse sonuc uretimi TEMSIL ETMEZ).
GEN_TOP_N = 6
GEN_CANDIDATE_N = 40
RETRIEVE_TOP_K = GEN_CANDIDATE_N   # k=10 ve k=20 raporu icin >=20 yeterli; 40 rerank icin de kullanilir


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
    chunks_by_id = {c.chunk_id: c for c in chunks}      # child + parent
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
    generator = Generator(retriever, reranker, chunks_by_id, span_meta, deepseek,
                          ders="biyoloji", abstain_score=0.30, module="eval")
    print(f"[eval] pipeline tamamen hazir ({time.time() - t0:.1f}s toplam)")
    return dict(doc=doc, chunks_by_id=chunks_by_id, span_meta=span_meta,
               retriever=retriever, reranker=reranker, generator=generator, children=children)


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


def _select_judge_ids(items: list[dict]) -> set[str]:
    """LLM-hakem PAHALI -> yalniz critical + 'birkac ornek' (gorev kosulu).
    Kural (id'ye degil ALANLARA dayanir -> golden set degisirse hala calisir):
      1) beklenen_davranis == 'cevapla' VE critical == true olan HER item.
      2) Adim 1'de HICBIR unitesi temsil edilmeyen unite'lerden (ornegin
         'Canlilar ve Cevre'de critical item yok) ilk 'cevapla' item'i -- her
         unitenin en az bir ornekle olculmesini garantiler."""
    ids: set[str] = set()
    seen_units: set[str] = set()
    for it in items:
        if it["beklenen_davranis"] != "cevapla":
            continue
        if it.get("critical"):
            ids.add(it["id"])
            if it.get("unite"):
                seen_units.add(it["unite"])
    for it in items:
        if it["beklenen_davranis"] != "cevapla" or it["id"] in ids:
            continue
        u = it.get("unite")
        if u and u not in seen_units:
            ids.add(it["id"])
            seen_units.add(u)
    return ids


def _eval_item(item: dict, pipeline: dict, judge: LlmJudge | None,
              judge_ids: set[str]) -> dict:
    item_id = item["id"]
    query = item["soru"]
    gold_spans = set(item.get("gold_kaynak_spanlar") or [])
    gold_pages = set(item.get("gold_sayfalar") or [])
    chunks_by_id = pipeline["chunks_by_id"]
    generator = pipeline["generator"]

    retr_metrics = M.RetrievalMetrics()
    contexts_for_judge = []
    if gold_spans:
        hits = _retry(lambda: pipeline["retriever"].retrieve(query, top_k=RETRIEVE_TOP_K),
                     label=f"retrieve[{item_id}]")
        span_sets, page_sets = _ranked_sets_for_hits(hits, chunks_by_id)
        retr_metrics = M.compute_retrieval_metrics(span_sets, page_sets, gold_spans, gold_pages)
        if item_id in judge_ids:
            contexts_for_judge = _retry(
                lambda: rerank_select(query, hits, chunks_by_id, pipeline["reranker"],
                                      top_n=GEN_TOP_N, candidate_n=GEN_CANDIDATE_N),
                label=f"rerank_select[{item_id}]")

    t0 = time.time()
    result = _retry(lambda: generator.answer(query, top_n=GEN_TOP_N, candidate_n=GEN_CANDIDATE_N),
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
        "id": item_id, "kategori": item["kategori"], "unite": item.get("unite"),
        "kazanim_kod": item.get("kazanim_kod"), "critical": bool(item.get("critical")),
        "beklenen_davranis": item["beklenen_davranis"],
        "zararli_kategori": item.get("zararli_kategori"),
        "soru": query,
        "retrieval": vars(retr_metrics),
        "citation": vars(citation_m),
        "guardrail": {"passed": guardrail_passed, "fail_closed": fail_closed,
                     "abstained": result.abstained, "reason": result.reason},
        "generation": {"text": result.text, "abstained": result.abstained,
                       "reason": result.reason, "n_citations": len(result.citations),
                       "invalid_citations": result.invalid_citations,
                       "cost_usd": result.cost_usd, "latency_s": gen_latency},
        "judge": judge_result,
    }


# --------------------------------------------------------------------------
# Aggregate + rapor
# --------------------------------------------------------------------------

_RETRIEVAL_KEYS = ["recall_at_10", "recall_at_20", "precision_at_10", "precision_at_20",
                  "mrr_value", "page_recall_at_10", "page_recall_at_20",
                  "page_precision_at_10", "page_precision_at_20", "page_mrr_value"]
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
    judge_agg = {k: M.mean([j.get(k) for j in judged]) for k in _JUDGE_KEYS}
    judge_agg["n_judged"] = len(judged)
    return {"n": n, "retrieval": retrieval, "citation": citation,
           "guardrail_pass_rate": guardrail_pass_rate, "n_guardrail_applicable": len(guardrail_vals),
           "fail_closed_rate": fail_closed_rate, "n_abstained": len(fc_vals),
           "judge": judge_agg}


def _weakness_score(it: dict) -> float:
    """Siralama icin TEK bir kompozit skor (dusuk = zayif). Guardrail
    UYGULANABILIR bir item'da BASARISIZSA sifir (en kotu) -- guvenlik/kapsam
    hatasi her zaman en kritik zayifliktir. Aksi halde mevcut (None olmayan)
    kalite sinyallerinin ortalamasi (retrieval recall@20, citation recall,
    faithfulness, answer_correctness)."""
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
              elapsed_s: float) -> str:
    lines = []
    lines.append(f"# Eval Raporu — golden_12bio_v0 ({golden.get('version')}) — TASLAK olcum")
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
    lines.append(f"- Toplam GERCEK DeepSeek maliyeti (bu eval kosusu, uretim+hakem): ${total_cost_usd:.6f}")
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
    lines.append(f"| recall@20 (span) | {_fmt(r.get('recall_at_20'))} |")
    lines.append(f"| precision@10 (span) | {_fmt(r.get('precision_at_10'))} |")
    lines.append(f"| precision@20 (span) | {_fmt(r.get('precision_at_20'))} |")
    lines.append(f"| MRR (span) | {_fmt(r.get('mrr_value'))} |")
    lines.append(f"| recall@10 (sayfa) | {_fmt(r.get('page_recall_at_10'))} |")
    lines.append(f"| recall@20 (sayfa) | {_fmt(r.get('page_recall_at_20'))} |")
    lines.append(f"| citation precision | {_fmt(c.get('precision'))} |")
    lines.append(f"| citation recall | {_fmt(c.get('recall'))} |")
    lines.append(f"| guardrail pass-rate (n={agg['n_guardrail_applicable']}) | {_fmt(agg['guardrail_pass_rate'])} |")
    lines.append(f"| fail-closed orani (n={agg['n_abstained']} abstain) | {_fmt(agg['fail_closed_rate'])} |")
    lines.append(f"| faithfulness (n={j['n_judged']}) | {_fmt(j.get('faithfulness'))} |")
    lines.append(f"| answer_relevancy (n={j['n_judged']}) | {_fmt(j.get('answer_relevancy'))} |")
    lines.append(f"| answer_correctness (n={j['n_judged']}) | {_fmt(j.get('answer_correctness'))} |")
    return "\n".join(lines)


def run(golden_path: str = GOLDEN_PATH, book_path: str = BOOK_PATH,
       results_dir: str = RESULTS_DIR) -> dict:
    _load_dotenv()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise RuntimeError("DEEPSEEK_API_KEY yok (.env kontrol et) -- gercek eval kosusu icin gerekli.")
    if not os.path.exists(book_path):
        raise FileNotFoundError(f"golden set kaynak PDF'i yok: {book_path}")

    t_start = time.time()
    golden = load_golden(golden_path)
    items = golden["items"]
    judge_ids = _select_judge_ids(items)
    print(f"[eval] {len(items)} item yuklendi ({golden_path}); "
         f"{len(judge_ids)} item LLM-hakem alacak: {sorted(judge_ids)}")

    pipeline = build_pipeline(book_path)
    judge = LlmJudge() if judge_ids else None

    items_out = []
    for i, item in enumerate(items, start=1):
        print(f"[eval] ({i}/{len(items)}) {item['id']}: {item['soru'][:70]!r}")
        it_out = _eval_item(item, pipeline, judge, judge_ids)
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
    json_path = os.path.join(results_dir, f"eval_v0_{ts}.json")
    md_path = os.path.join(results_dir, f"eval_v0_{ts}.md")

    payload = {
        "meta": {
            "golden_path": golden_path, "golden_version": golden.get("version"),
            "book_path": book_path, "generated_at_utc": ts,
            "judge_method": JUDGE_METHOD, "deepeval_available": DEEPEVAL_AVAILABLE,
            "judged_item_ids": sorted(judge_ids), "n_items": len(items_out),
            "total_cost_usd": total_cost_usd, "elapsed_s": elapsed_s,
            "gen_top_n": GEN_TOP_N, "gen_candidate_n": GEN_CANDIDATE_N,
        },
        "overall": overall, "by_category": by_category, "items": items_out,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    md = _md_report(golden, items_out, overall, by_category, total_cost_usd,
                    JUDGE_METHOD, judge_ids, elapsed_s)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n[eval] TAMAM ({elapsed_s:.1f}s). JSON: {json_path}")
    print(f"[eval] MD: {md_path}")
    print(f"[eval] toplam gercek DeepSeek maliyeti (bu kosuda): ${total_cost_usd:.6f}")
    return payload


def main() -> None:
    run()


if __name__ == "__main__":
    main()
