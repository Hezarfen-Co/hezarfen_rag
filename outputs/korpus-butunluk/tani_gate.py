"""Kanit kapisi tanisi: sayfa hizalama rerank skorlarini dusurdu mu?"""
import sys, time; sys.path.insert(0, ".")
from src.ingest.canonical import build_canonical
from src.chunk import chunk_document
from src.embed import BGEM3Embedder
from src.index import DenseIndex, BM25Index
from src.retrieve import SparseIndex, HybridRetriever
from src.rerank import BGEReranker, rerank_select

SORULAR = ["Mitoz nedir?", "Mayoz bölünme nedir?", "Kalıtım nedir?",
           "Canlılarda hücre bölünmesi neden gereklidir?", "Ekosistem nedir?"]
doc = build_canonical("data/lise/10/biyoloji/kitap.pdf", sinif="10", ders="biyoloji")
emb, rr = BGEM3Embedder(), BGEReranker()

for aligned in (True, False):
    kids = [c for c in chunk_document(doc, page_aligned=aligned) if c.level == "child"]
    ids = [c.chunk_id for c in kids]; texts = [c.text for c in kids]
    _, vecs = emb.embed_chunks(kids, batch_size=32)
    retr = HybridRetriever(emb, DenseIndex(dim=1024).build(ids, vecs),
                           BM25Index().build(ids, texts),
                           SparseIndex().build(ids, emb.embed_sparse(texts, batch_size=32)))
    by_id = {c.chunk_id: c for c in kids}
    print(f"\n=== page_aligned={aligned} ({len(kids)} chunk) ===")
    for q in SORULAR:
        hits = retr.retrieve(q, top_k=40)
        ctxs = rerank_select(q, hits, by_id, rr, top_n=6, candidate_n=40)
        top = ctxs[0].score if ctxs else float("nan")
        print(f"  {q:45} top_skor={top:+.4f}  kapi(0.30)={'GECER' if top>=0.30 else 'RED'}"
              f"  ilk_metin={ctxs[0].text[:60]!r}" if ctxs else "  (bos)")
