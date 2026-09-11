"""#53 ablation -- retrieval VEKIL olcumu (golden set ENGELLI, bkz. #92).

DURUST SINIR: bu bir GOLDEN SET olcumu DEGILDIR. Gercek kapi kararini golden
set verir (#92 cozulunce). Burada yapilan "needle" testi: kitaptan rastgele
secilen bir birimin KENDI metni sorgu olarak kullanilir, gold = o span'i
iceren chunk. Sorgu ile gold chunk arasinda birebir sozcuk ortusmesi oldugu
icin mutlak sayilar GERCEK SORULARDAN KOLAY; ama iki yapilandirma AYNI
sorgularla, AYNI tohumla, AYNI boru hattiyla olculdugu icin FARK anlamlidir.
Ablation'in sordugu soru zaten "hangisi daha iyi", "mutlak deger ne" degil.

Ek olarak, birebir ortusmeyi kiran ikinci bir sorgu kumesi de kosulur:
birimin yalniz ILK YARISI sorgu yapilir ve chunk metninden o yari cikarilir
-> sozcuk ortusmesi dusuk, dense/sparse'a gercek is duser.
"""
import json, random, statistics, sys, time
sys.path.insert(0, ".")
from src.ingest.canonical import build_canonical
from src.chunk import chunk_document
from src.embed import BGEM3Embedder
from src.index import DenseIndex, BM25Index
from src.retrieve import SparseIndex, HybridRetriever

SEED = 20260911
N_SORGU = 200
BOOK = "data/lise/10/biyoloji/kitap.pdf"

doc = build_canonical(BOOK, sinif="10", ders="biyoloji")
emb = BGEM3Embedder()

# sorgular: yeterince uzun retrievable birimler (her iki config'te de AYNI)
rng = random.Random(SEED)
adaylar = [u for u in doc.retrievable_units if len(u.text.split()) >= 25]
secili = rng.sample(adaylar, min(N_SORGU, len(adaylar)))
print(f"aday birim: {len(adaylar)}, secilen sorgu: {len(secili)}")

def sorgu_tam(u):
    return " ".join(u.text.split()[:40])

def sorgu_yarim(u):
    w = u.text.split()
    return " ".join(w[:len(w)//2][:30])

def kur(aligned):
    ch = chunk_document(doc, page_aligned=aligned)
    kids = [c for c in ch if c.level == "child"]
    ids = [c.chunk_id for c in kids]
    texts = [c.text for c in kids]
    t0 = time.time()
    _, vecs = emb.embed_chunks(kids, batch_size=32)
    sp = emb.embed_sparse(texts, batch_size=32)
    print(f"  embed {len(kids)} chunk: {time.time()-t0:.1f}s")
    r = HybridRetriever(emb, DenseIndex(dim=1024).build(ids, vecs),
                        BM25Index().build(ids, texts),
                        SparseIndex().build(ids, sp))
    span2chunk = {}
    for c in kids:
        for sid in c.span_ids:
            span2chunk.setdefault(sid, set()).add(c.chunk_id)
    by_id = {c.chunk_id: c for c in kids}
    return r, span2chunk, by_id

def kosum(retr, span2chunk, by_id, sorgu_fn, etiket):
    rec5 = rec10 = rec20 = 0; rr = []; sayfa_p = []; sayfa_dogru = 0
    n = 0
    for u in secili:
        gold = span2chunk.get(u.span_id)
        if not gold:
            continue
        n += 1
        q = sorgu_fn(u)
        hits = [cid for cid, _ in retr.retrieve(q, top_k=20)]
        rec5 += any(c in gold for c in hits[:5])
        rec10 += any(c in gold for c in hits[:10])
        rec20 += any(c in gold for c in hits[:20])
        sira = next((i+1 for i, c in enumerate(hits) if c in gold), None)
        rr.append(1.0/sira if sira else 0.0)
        # sayfa hassasiyeti vekili: top-1 chunk'in kapsadigi sayfalar ic. dogru sayfa
        if hits:
            c = by_id[hits[0]]
            kapsanan = set(range(c.page_start, c.page_end + 1))
            sayfa_p.append(1.0/len(kapsanan) if u.page in kapsanan else 0.0)
            sayfa_dogru += (u.page in kapsanan)
    return {"etiket": etiket, "n": n,
            "recall@5": round(rec5/n, 4), "recall@10": round(rec10/n, 4),
            "recall@20": round(rec20/n, 4), "mrr": round(statistics.mean(rr), 4),
            "top1_sayfa_precision": round(statistics.mean(sayfa_p), 4),
            "top1_sayfa_isabet": round(sayfa_dogru/n, 4)}

sonuc = {}
for aligned, ad in ((False, "eski_serbest"), (True, "yeni_sayfa_hizali")):
    print(f"--- {ad} ---")
    retr, s2c, by_id = kur(aligned)
    sonuc[ad] = {
        "tam_metin_sorgu": kosum(retr, s2c, by_id, sorgu_tam, "tam"),
        "yarim_metin_sorgu": kosum(retr, s2c, by_id, sorgu_yarim, "yarim"),
    }
    print(json.dumps(sonuc[ad], indent=2, ensure_ascii=False))

json.dump({"kitap": BOOK, "seed": SEED, "n_sorgu": len(secili), "sonuc": sonuc},
          open(sys.argv[1] if len(sys.argv) > 1 else "ablation_retrieval.json", "w"),
          indent=2, ensure_ascii=False)
