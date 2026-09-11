"""Faz — Backend-hazır HTTP servisi (#2/D3). RagService'i (transport-bağımsız iş
mantığı) FastAPI ile sarar: API-CONTRACT.md'deki /rag/chat + /rag/summarize +
/rag/questions + /health. Backend bu HTTP'yi çağırır (o da front'a döner) — böylece
RAG repo'su "backend'e hazır" olur; backend/front'a bu repodan DOKUNULMAZ.

GÜVENLİK: `role` istek gövdesinde gelir ve SUNUCU-TARAFI türetilmiş kabul edilir —
gerçek üretimde bu HTTP servisi backend'in ARKASINDA (iç ağ) çalışır ve role'ü
backend'in auth katmanı doldurur; servis onu doğrulamaz (RES-002/003).

Çalıştırma:  python -m src.service.http_app   (env: BOOK_PATH, SINIF, DERS)
Test:        create_app(stub_service) + fastapi.testclient.TestClient  (model gerekmez)
"""
from __future__ import annotations

import os

from pydantic import BaseModel, Field


class RoleModel(BaseModel):
    role: str
    sinif: str | None = None
    ders_list: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    query: str
    history: list[dict] | None = None
    role: RoleModel | None = None
    options: dict = Field(default_factory=dict)


class ScopeModel(BaseModel):
    pages: list[int] | None = None
    span_ids: list[str] | None = None
    ders: str | None = None
    sinif: str | None = None
    scope_label: str = ""


class SummarizeRequest(BaseModel):
    scope: ScopeModel
    role: RoleModel | None = None


class QuestionsRequest(BaseModel):
    scope: ScopeModel
    role: RoleModel | None = None
    n: int = 5
    difficulty: str = "orta"
    seed_question: str | None = None


def create_app(service):
    """RagService'i saran FastAPI uygulaması. `service` enjekte edilir (test'te stub;
    üretimde build_service()). Model yüklemez — yalnız HTTP↔handler eşlemesi."""
    from fastapi import FastAPI

    app = FastAPI(title="Hezarfen RAG", version="1.0",
                  description="Kaynakla-konuşma + kanıtlı özet + benzer-soru (API-CONTRACT.md)")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/rag/chat")
    def chat(req: ChatRequest):
        return service.chat(req.model_dump())

    @app.post("/rag/summarize")
    def summarize(req: SummarizeRequest):
        return service.summarize(req.model_dump())

    @app.post("/rag/questions")
    def questions(req: QuestionsRequest):
        return service.generate_questions(req.model_dump())

    return app


# M0-7 (#39): parent genisletme eval ile uretimde FARKLI davraniyordu (ACC-10).
# Tek anahtar: `RAG_INCLUDE_PARENTS` (varsayilan 0 = uretimin bugunku davranisi).
# eval/runner.py AYNI anahtari okur -> iki yol artik ayrisamaz. Hangi degerin
# dogru oldugu A/B ile karara baglanacak (#39 kabul kriteri).
INCLUDE_PARENTS_DEFAULT = os.environ.get("RAG_INCLUDE_PARENTS", "0") not in ("0", "", "false", "False")


def build_service(book_path: str, *, sinif: str, ders: str, corpus_version: str = "",
                  ocr: bool = False, vlm: bool = False,
                  include_parents: bool | None = None):
    """Gerçek pipeline'ı kurup RagService döndürür (ağır: PDF parse + BGE modelleri +
    indeks). main()/üretim için. corpus_version cache anahtarına girer (#30).

    `include_parents`: parent chunk'lar `chunks_by_id`'ye girsin mi (yani
    `rerank_select` parent genisletmesi ETKIN olsun mu). None -> env varsayilani."""
    if include_parents is None:
        include_parents = INCLUDE_PARENTS_DEFAULT
    from ..ingest.canonical import build_canonical
    from ..chunk import chunk_document
    from ..embed import BGEM3Embedder
    from ..index import DenseIndex, BM25Index
    from ..retrieve import SparseIndex, HybridRetriever
    from ..rerank import BGEReranker
    from ..generate import Generator, QuestionGenerator, build_span_meta
    from ..summarize.summarizer import Summarizer
    from ..guard.llm_classifier import LLMSafetyClassifier
    from .handler import RagService

    doc = build_canonical(book_path, sinif=sinif, ders=ders, ocr=ocr, vlm=vlm)
    cv = corpus_version or doc.source_version[:12]
    all_chunks = chunk_document(doc)
    children = [c for c in all_chunks if c.level == "child"]
    ids = [c.chunk_id for c in children]
    texts = [c.text for c in children]
    # M0-7 (#39) -- EXP-010/ACC-10: BU SATIR SESSIZ BIR AYRISMAYDI.
    # Eskiden `by_id` yalniz CHILD chunk'lari tasiyordu; `rerank_select`'teki
    # `ch.parent_id in chunks_by_id` kontrolu bu yuzden daima False oluyor ve
    # PARENT GENISLETME uretimde sessizce KAPALI kaliyordu. `src/eval/runner.py`
    # ise child+parent koyuyordu -> ACIK. Yani yayinlanmis 0.645/0.883 sayilari
    # uretimde kosan boru hattini TEMSIL ETMIYORDU.
    # Artik davranis TEK YERDEN, acikca secilir (ikisi ayni anahtari okur).
    # Varsayilan False = uretimin BUGUNKU davranisi; degistirmek icin A/B gerekiyor
    # (parent genisletme ACC-03'e gore atifi yanlis sayfaya kaydiriyor).
    by_id = ({c.chunk_id: c for c in all_chunks} if include_parents
             else {c.chunk_id: c for c in children})
    emb = BGEM3Embedder()
    _, vecs = emb.embed_chunks(children, batch_size=16)
    meta = {c.chunk_id: {"sinif": sinif, "ders": ders} for c in children}
    retr = HybridRetriever(emb, DenseIndex(dim=1024).build(ids, vecs),
                           BM25Index().build(ids, texts),
                           SparseIndex().build(ids, emb.embed_sparse(texts, batch_size=16)),
                           meta=meta)
    span_meta = build_span_meta(doc)
    gen = Generator(retr, BGEReranker(), by_id, span_meta, ders=ders,
                    safety_classifier=LLMSafetyClassifier(), context_packing=True,
                    corpus_version=cv, require_role=True)   # STRICT: rolsüz istek fail-closed
    return RagService(gen, doc=doc, summarizer=Summarizer(),
                      question_gen=QuestionGenerator(), ders=ders)


def main() -> None:
    import uvicorn
    book = os.environ.get("BOOK_PATH", "data/lise/12/biyoloji/kitap.pdf")
    sinif = os.environ.get("SINIF", "12")
    ders = os.environ.get("DERS", "biyoloji")
    print(f"[http] pipeline kuruluyor: {book} ({sinif}/{ders}) — model yüklenecek...")
    service = build_service(book, sinif=sinif, ders=ders)
    app = create_app(service)
    print("[http] hazır → http://127.0.0.1:8000  (/health, /rag/chat, /rag/summarize, /rag/questions)")
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
