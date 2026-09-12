"""#59 ablation — ilgililik tabanli secim, IKI YONDE olculur.

A) ayni-parent gold cifti   -> eski kuralin sifirladigi durum
B) FARKLI-parent gold cifti -> kisiti kaldirmanin zarar verip vermedigi

Tek yonlu olcum YANILTIR: ilk ablation yapisi geregi ayni-parent'i
odullendiriyordu ve tek basina varsayilani belirleyemezdi.

HIZ: uc kural AYNI sorgu icin AYNI aday kumesini yeniden siralar; yalniz
SECIM degisir. Bu yuzden rerank sorgu basina BIR KEZ kosulur ve uc kural
onbellege alinmis siralamaya uygulanir (720 -> 240 rerank cagrisi).
"""
import json, random, statistics, sys
sys.path.insert(0, ".")
from src.ingest.canonical import build_canonical
from src.chunk import chunk_document
from src.embed import BGEM3Embedder
from src.index import DenseIndex, BM25Index
from src.retrieve import SparseIndex, HybridRetriever
from src.rerank import BGEReranker, rerank_select

SEED, N, TOP_N = 20260912, 120, 6
KITAP = "data/lise/10/biyoloji/kitap.pdf"


class _Cached:
    """Onceden hesaplanmis siralamayi geri oynatan reranker."""
    def __init__(self, ranked):
        self.ranked = ranked

    def rerank(self, query, items, top_k=None, normalize=True):
        izin = {cid for cid, _ in items}
        out = [(cid, sc) for cid, sc in self.ranked if cid in izin]
        return out[:top_k] if top_k else out


def main(cikti):
    doc = build_canonical(KITAP, sinif="10", ders="biyoloji")
    kids = [c for c in chunk_document(doc) if c.level == "child"]
    ids = [c.chunk_id for c in kids]; texts = [c.text for c in kids]
    emb, rr = BGEM3Embedder(), BGEReranker()
    _, vecs = emb.embed_chunks(kids, batch_size=32)
    retr = HybridRetriever(emb, DenseIndex(dim=1024).build(ids, vecs),
                           BM25Index().build(ids, texts),
                           SparseIndex().build(ids, emb.embed_sparse(texts, batch_size=32)))
    by_id = {c.chunk_id: c for c in kids}

    gruplar = {}
    for c in kids:
        if c.parent_id:
            gruplar.setdefault(c.parent_id, []).append(c)
    uzun = [c for c in kids if len(c.text.split()) >= 20 and c.parent_id]

    rng = random.Random(SEED)
    ayni = [(g[i], g[i + 1]) for g in gruplar.values() if len(g) >= 2
            for i in range(len(g) - 1)
            if len(g[i].text.split()) >= 20 and len(g[i + 1].text.split()) >= 20]
    ayni = rng.sample(ayni, min(N, len(ayni)))
    rng2 = random.Random(SEED)
    farkli = []
    while len(farkli) < N:
        a, b = rng2.sample(uzun, 2)
        if a.parent_id != b.parent_id:
            farkli.append((a, b))
    print(f"ayni-parent cift: {len(ayni)}, farkli-parent cift: {len(farkli)}", flush=True)

    def hazirla(ciftler, etiket):
        """Her cift icin (sorgu, siralanmis adaylar) -- rerank BIR KEZ."""
        out = []
        for i, (a, b) in enumerate(ciftler, 1):
            q = " ".join(a.text.split()[:22] + b.text.split()[:22])
            hits = retr.retrieve(q, top_k=40)
            cand = [(cid, by_id[cid].text) for cid, _ in hits if cid in by_id][:40]
            out.append((q, hits, rr.rerank(q, cand), a, b))
            if i % 30 == 0:
                print(f"  [{etiket}] {i}/{len(ciftler)} rerank", flush=True)
        return out

    hazir = {"ayni_parent": hazirla(ayni, "ayni"),
             "farkli_parent": hazirla(farkli, "farkli")}

    def kosum(veri, **kw):
        tam = kismi = hic = 0
        ilgisiz, secilen, sayfa = [], [], []
        for q, hits, ranked, a, b in veri:
            ctxs = rerank_select(q, hits, by_id, _Cached(ranked),
                                 top_n=TOP_N, candidate_n=40, **kw)
            bul = {c.chunk_id for c in ctxs}
            n = len({a.chunk_id, b.chunk_id} & bul)
            tam += n == 2; kismi += n == 1; hic += n == 0
            secilen.append(len(ctxs))
            ilgisiz.append(sum(1 for c in ctxs if c.score < 0.05) / max(1, len(ctxs)))
            sayfa.append(len({p for c in ctxs
                              for p in range(by_id[c.chunk_id].page_start,
                                             by_id[c.chunk_id].page_end + 1)}))
        m = len(veri)
        return {"all_evidence_recall": round(tam / m, 4),
                "kismi": round(kismi / m, 4), "hic": round(hic / m, 4),
                "secilen_ort": round(statistics.mean(secilen), 2),
                "ilgisiz_oran": round(statistics.mean(ilgisiz), 4),
                "sayfa_ort": round(statistics.mean(sayfa), 2)}

    kurallar = {
        "eski (yapisal, share=1.0)": dict(diversity_share=1.0, relevance_min=0.0,
                                          relevance_rel=0.0),
        "yeni (ilgililik esigi)": dict(),
        "esik YOK (saf skor)": dict(relevance_min=0.0, relevance_rel=0.0),
    }
    sonuc = {}
    for ad, kw in kurallar.items():
        sonuc[ad] = {yon: kosum(hazir[yon], **kw) for yon in hazir}
        print(f"\n### {ad}", flush=True)
        for yon in ("ayni_parent", "farkli_parent"):
            r = sonuc[ad][yon]
            print(f"  {yon:14} all_ev={r['all_evidence_recall']:.3f} "
                  f"kismi={r['kismi']:.3f} hic={r['hic']:.3f} "
                  f"secilen={r['secilen_ort']} ilgisiz={r['ilgisiz_oran']:.3f} "
                  f"sayfa={r['sayfa_ort']}", flush=True)
    json.dump({"seed": SEED, "n": N, "top_n": TOP_N, "kitap": KITAP, "sonuc": sonuc},
              open(cikti, "w"), ensure_ascii=False, indent=2)
    print(f"\n[yazildi] {cikti}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ablation.json")
