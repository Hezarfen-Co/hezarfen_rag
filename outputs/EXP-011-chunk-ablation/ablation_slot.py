"""#53 -- bayrak edilen RISKIN dogrudan olcumu: sayfa hizalama kucuk parcalar
uretiyor; bunlar top-k yuvalarini isgal edip baglam kalitesini dusuruyor mu?

Bu olcum recall'dan BAGIMSIZ: gold bulunsa bile kalan 4 yuva cop parcayla
dolarsa uretici modele giden baglam fakirlesir (Lost-in-the-Middle degil,
dogrudan BILGI YOKLUGU)."""
import json, random, statistics, sys
sys.path.insert(0, ".")
from src.ingest.canonical import build_canonical
from src.chunk import chunk_document
from src.embed import BGEM3Embedder
from src.index import DenseIndex, BM25Index
from src.retrieve import SparseIndex, HybridRetriever

SEED, N = 20260911, 200
doc = build_canonical("data/lise/10/biyoloji/kitap.pdf", sinif="10", ders="biyoloji")
emb = BGEM3Embedder()
rng = random.Random(SEED)
secili = rng.sample([u for u in doc.retrievable_units if len(u.text.split()) >= 25], N)

out = {}
for aligned, ad in ((False, "eski_serbest"), (True, "yeni_sayfa_hizali")):
    kids = [c for c in chunk_document(doc, page_aligned=aligned) if c.level == "child"]
    ids = [c.chunk_id for c in kids]; texts = [c.text for c in kids]
    _, vecs = emb.embed_chunks(kids, batch_size=32)
    retr = HybridRetriever(emb, DenseIndex(dim=1024).build(ids, vecs),
                           BM25Index().build(ids, texts),
                           SparseIndex().build(ids, emb.embed_sparse(texts, batch_size=32)))
    by_id = {c.chunk_id: c for c in kids}
    kucuk_yuva5, top5_tok, kucuk_gorulen = [], [], set()
    for u in secili:
        hits = [cid for cid, _ in retr.retrieve(" ".join(u.text.split()[:40]), top_k=20)][:5]
        toks = [by_id[c].approx_tokens for c in hits]
        top5_tok.append(sum(toks))
        kucuk_yuva5.append(sum(1 for t in toks if t < 50))
        kucuk_gorulen |= {c for c in hits if by_id[c].approx_tokens < 50}
    korpus_kucuk = sum(1 for c in kids if c.approx_tokens < 50)
    out[ad] = {
        "chunk": len(kids),
        "korpusta_50_alti": korpus_kucuk,
        "korpusta_50_alti_oran": round(korpus_kucuk/len(kids), 4),
        "top5te_50_alti_ort_yuva": round(statistics.mean(kucuk_yuva5), 3),
        "top5te_hic_50_alti_goren_sorgu_orani": round(
            sum(1 for k in kucuk_yuva5 if k > 0)/len(kucuk_yuva5), 4),
        "top5_toplam_token_ort": round(statistics.mean(top5_tok), 1),
        "top5_toplam_token_medyan": statistics.median(top5_tok),
        "farkli_kucuk_chunk_top5e_girdi": len(kucuk_gorulen),
    }
    print(ad, json.dumps(out[ad], ensure_ascii=False))
json.dump(out, open(sys.argv[1], "w"), indent=2, ensure_ascii=False)
