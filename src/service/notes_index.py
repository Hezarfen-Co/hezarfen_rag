"""`rag.index` — the write path: note + attachments → chunks → vectors → the
note index (`src/index/notes.py`), and the answer object the backend stores.

WHAT ONE REQUEST DOES

  1. the note's own `title` + `content` become one document (always);
  2. each `files[]` entry is read as **bytes over its own QUIC blob stream**
     (`BlobRequest` → `BlobResponse` header → exactly `size` raw bytes), then
     parsed by content type — PDFs through the same canonical loader the
     textbook corpus uses (`ingest/canonical.build_canonical`), plain text
     decoded directly;
  3. every document is chunked (`chunk.chunk_document`) and embedded in one
     pass (`embed_both`: dense + sparse, the provider configured by
     `RAG_EMBED_*`);
  4. the note's rows replace whatever this note held before (one unit — a
     re-index cannot duplicate);
  5. the answer echoes `files[].id` so the backend can stamp the doc id it
     minted onto the attachment row, and names any attachment that failed.

A FAILED ATTACHMENT DOES NOT ABORT THE INDEX. A blob read that refuses (missing
file, permission, unknown type) is recorded and the rest — including the note
body — is indexed: a partly indexed note beats no note. The backend keeps the
previous `rag_output` rows when the whole round trip fails, which is why a
refusal must be typed rather than answered with an empty "ok".
"""
from __future__ import annotations

import os
import tempfile

from ..bridge.contract import BlobReadRefused, RagIndexPayload
from ..index.notes import (MAX_NOTE_FILE_BYTES, doc_id_for_bytes,
                           shared_note_index)

PDF_TYPES = ("application/pdf", "application/x-pdf")
TEXT_TYPES = ("text/plain", "text/markdown", "text/csv", "application/json")


def _is_pdf(name: str, content_type: str) -> bool:
    return (content_type or "").lower() in PDF_TYPES or \
        (name or "").lower().endswith(".pdf")


def _text_units(doc, text: str, *, page: int = 1):
    """`text` → canonical units (one per non-empty paragraph).

    The chunker consumes `CanonicalUnit`s, so the note's own prose rides the
    exact same pipeline as a parsed PDF page — no second chunker, no second
    span scheme.
    """
    from ..ingest.canonical import CanonicalUnit, make_span_id
    units = []
    for n, parca in enumerate(p for p in text.split("\n") if p.strip()):
        units.append(CanonicalUnit(
            span_id=make_span_id(doc.doc_id, page, n), doc_id=doc.doc_id,
            sinif=doc.sinif, ders=doc.ders, kaynak_turu=doc.kaynak_turu,
            page=page, bbox=(0.0, 0.0, 0.0, 0.0), block_no=n,
            kind="paragraph", text=parca.strip(), page_visual="low_visual",
            retrieval_disi=False))
    return units


def _body_doc(payload: RagIndexPayload):
    """The note's own title + content — doc id is the note's own record key,
    so a re-index replaces rows instead of piling up new ones."""
    from ..ingest.canonical import CanonicalDoc
    doc = CanonicalDoc(source_path="", doc_id=payload.course_note,
                       source_version=payload.course_note, sinif="", ders="",
                       kaynak_turu="konu_ozeti", page_count=1)
    doc.units = _text_units(doc, f"{payload.title}\n{payload.content}")
    return doc


def _plain_doc(name: str, data: bytes, *, doc_id: str):
    from ..ingest.canonical import CanonicalDoc
    metin = data.decode("utf-8", errors="replace")
    doc = CanonicalDoc(source_path=name, doc_id=doc_id,
                       source_version=doc_id, sinif="", ders="",
                       kaynak_turu="konu_ozeti", page_count=1)
    doc.units = _text_units(doc, metin)
    return doc


def _pdf_doc(name: str, data: bytes, *, doc_id: str):
    """PDF bytes → canonical document, through the corpus's own loader.

    `build_canonical` reads a path, so the bytes land in a temp file first; the
    doc id is computed from the bytes here (not from the temp path) so it stays
    the content hash the citation resolver expects.
    """
    from ..ingest.canonical import build_canonical
    fd, yol = tempfile.mkstemp(suffix=".pdf", prefix="not-eki-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        doc = build_canonical(yol, sinif="", ders="", kaynak_turu="konu_ozeti")
        doc.source_path = name
        doc.doc_id = doc_id                 # sha256 of the same bytes
        for unit in doc.units:
            unit.doc_id = doc_id
            unit.span_id = unit.span_id.replace(doc.doc_id, doc_id, 0) \
                if unit.span_id.startswith(doc.doc_id) else unit.span_id
        return doc
    finally:
        try:
            os.unlink(yol)
        except OSError:
            pass


def _chunks_for(doc, course_note: str):
    """Children only, note-scoped ids (two notes sharing one PDF must not
    collide), no parent links (no parent rows are stored)."""
    from ..chunk import chunk_document
    out = []
    for chunk in chunk_document(doc):
        if chunk.level != "child":
            continue
        chunk.chunk_id = f"{course_note}:{chunk.chunk_id}"
        chunk.parent_id = None
        out.append(chunk)
    return out


def index_course_note(payload: RagIndexPayload, *, school: str,
                      blob_reader=None, note_index=None, embedder=None) -> dict:
    """Index one course note and return the answer object the backend stores."""
    index = note_index if note_index is not None else shared_note_index()
    if embedder is None:
        from ..embed.provider import build_embedder
        embedder = build_embedder()

    docs = [_body_doc(payload)]
    indexed_files, failed_files = [], []

    for meta in payload.files:
        try:
            header, data = _read_file(meta, school=school,
                                      author=payload.author, blob_reader=blob_reader)
        except BlobReadRefused as exc:
            failed_files.append({"id": meta.id, "name": meta.name,
                                 "code": exc.code, "message": exc.message})
            continue
        name = str(header.get("name") or meta.name or "")
        content_type = str(header.get("content_type") or meta.content_type or "")
        doc_id = doc_id_for_bytes(data)
        try:
            if _is_pdf(name, content_type):
                doc = _pdf_doc(name, data, doc_id=doc_id)
            elif (content_type or "").lower() in TEXT_TYPES or \
                    name.lower().endswith((".txt", ".md", ".csv", ".json")):
                doc = _plain_doc(name, data, doc_id=doc_id)
            else:
                raise BlobReadRefused("unsupported_type",
                                      f"'{content_type or 'bilinmeyen'}' türü "
                                      "indekslenemiyor")
        except BlobReadRefused as exc:
            failed_files.append({"id": meta.id, "name": name,
                                 "code": exc.code, "message": exc.message})
            continue
        except Exception as exc:                        # noqa: BLE001
            failed_files.append({"id": meta.id, "name": name, "code": "parse_failed",
                                 "message": f"{type(exc).__name__}: {exc}"})
            continue
        docs.append(doc)
        indexed_files.append({"id": meta.id, "doc_id": doc_id, "name": name})

    chunks = []
    for doc in docs:
        chunks.extend(_chunks_for(doc, payload.course_note))
    rows = []
    if chunks:
        texts = [c.text for c in chunks]
        vecs, sparse = embedder.embed_both(texts, batch_size=16)
        rows = [(chunk, vec, sp) for chunk, vec, sp in zip(chunks, vecs, sparse)]
    n = index.replace_note(school, payload.course_note, rows)

    return {
        "course_note": payload.course_note,
        "chunks": n,
        "files": indexed_files,
        "failed": failed_files,
        "summary": _summary(payload.title, n, indexed_files, failed_files),
    }


def _read_file(meta, *, school: str, author: str, blob_reader):
    """One attachment's bytes over its own blob stream.

    The request shape is the bridge's (`protocol.rs::BlobRequest`): the file's
    record id, the school slug, and the note's author as `on_behalf_of` — the
    `ai` principal can view no course, so a read as itself always earns
    `forbidden`.
    """
    if blob_reader is None:
        raise BlobReadRefused("blob_unavailable",
                              "bu servis örnekte blob okuma yolu yok")
    if int(meta.size or 0) > MAX_NOTE_FILE_BYTES:
        raise BlobReadRefused("too_large",
                              f"ek {meta.size} bayt: sınır {MAX_NOTE_FILE_BYTES}")
    return blob_reader.read({"id": meta.id, "school": school, "file": meta.id,
                             "on_behalf_of": author},
                            max_bytes=MAX_NOTE_FILE_BYTES)


def _summary(title: str, chunks: int, indexed_files, failed_files) -> str:
    """One or two Turkish sentences — the human is the reader of this payload."""
    baslik = (title or "").strip() or "Ders notu"
    ek = (f", {len(indexed_files)} ek dosyayla" if indexed_files else "")
    metin = (f"'{baslik}' notu indekslendi: {chunks} metin parçası{ek}. "
             "Bu not artık sorularda kaynak olarak kullanılabilir.")
    if failed_files:
        adlar = ", ".join(str(f.get("name") or f.get("id")) for f in failed_files)
        metin += (f" Şu ekler okunamadı ve indekslenemedi: {adlar} — "
                  "notun kendi metni yine de indekslendi.")
    return metin
