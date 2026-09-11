"""#53 ablation: sayfa hizali chunk'lama -- yapisal olcum (gercek kitap)."""
import json, statistics, sys, time
sys.path.insert(0, ".")
from src.ingest.canonical import build_canonical
from src.chunk import chunk_document

BOOK = "data/lise/10/biyoloji/kitap.pdf"
t0 = time.time()
doc = build_canonical(BOOK, sinif="10", ders="biyoloji")
print(f"canonical: {len(doc.units)} birim, {len(doc.retrievable_units)} retrievable, {time.time()-t0:.1f}s")

def olc(aligned):
    ch = chunk_document(doc, page_aligned=aligned)
    kids = [c for c in ch if c.level == "child"]
    par = [c for c in ch if c.level == "parent"]
    asan = [c for c in kids if c.page_start != c.page_end]
    tok = [c.approx_tokens for c in kids]
    sayfa_sayisi = [c.page_end - c.page_start + 1 for c in kids]
    return {
        "child": len(kids), "parent": len(par),
        "asan": len(asan), "asan_oran": round(len(asan)/max(1,len(kids)), 4),
        "tok_ort": round(statistics.mean(tok), 1),
        "tok_medyan": statistics.median(tok),
        "tok_p10": round(statistics.quantiles(tok, n=10)[0], 1),
        "tok_min": min(tok), "tok_max": max(tok),
        "tok_150_alti": sum(1 for t in tok if t < 150),
        "tok_50_alti": sum(1 for t in tok if t < 50),
        "ort_sayfa_per_chunk": round(statistics.mean(sayfa_sayisi), 3),
        "tavan_precision_page": round(min(1.0, 1.24/statistics.mean(sayfa_sayisi)), 4),
    }

eski, yeni = olc(False), olc(True)
print(json.dumps({"eski_serbest": eski, "yeni_sayfa_hizali": yeni}, indent=2, ensure_ascii=False))
json.dump({"kitap": BOOK, "eski_serbest": eski, "yeni_sayfa_hizali": yeni},
          open("/tmp/claude-1000/-home-kadiryonak-Masa-st--Kodlama-HelloWorld-Hezarfen/7e625451-435a-4ee1-8e34-606a2eb6ae48/scratchpad/ablation_yapisal.json","w"),
          indent=2, ensure_ascii=False)
