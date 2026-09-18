"""The course-note index — the retrieval channel `rag.index` fills.

WHY IT IS ITS OWN INDEX. A textbook corpus is a file on disk
(`data/<school>/<kasa>/<sinif>/<ders>/kitap.pdf`) keyed by `(school, sinif,
ders)`. A course note names none of those on the wire: the `rag.index` payload
carries the note's `course` **uuid**, while a `rag.chat` scope pair carries a
class grade and a course **title** (derived by the backend from the asker's own
memberships) — and the backend's AI-read allowlist has no route that would let
this service resolve one to the other. There is no join, so a note cannot be
filed under a subject corpus.

WHAT IT IS INSTEAD. One bucket per **school** — the tenant dimension every store
already filters on, by exact equality (`guard/tenant.py`). `replace_note()` swaps
a note's rows as one unit (a re-index never duplicates); `retrieve()` ranks that
bucket's rows and `rag.chat` merges the hits into the subject corpus's.

HONEST LIMIT — the (class, subject) gate does not reach here. `can_access`
isolates class+subject for textbook chunks; a note carries neither on the wire,
so its rows cannot be checked against the asker's scope pairs. The backend still
refuses to *link* a citation the asker may not open (it stores `file: null`),
but a note's *text* from another course of the same school can be quoted.
Closing that needs the note's class+subject on the `rag.index` payload — a wire
change owned by the backend, not by this repo.

IN-MEMORY, DERIVED, DISPOSABLE. Nothing here is a source of truth: a restart
loses it, and any note edit re-dispatches `rag.index` — the backend's own model
of a `rag_output` row ("derived data").
"""
from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping

import numpy as np

from src.index.dense import DenseIndex
from src.index.lexical import BM25Index
from src.retrieve.rrf import rrf_fuse
from src.retrieve.sparse import SparseIndex

#: One attachment's byte ceiling — the backend's own `MAX_MAX_FILE_BYTES`
#: (`constant.rs:80`). A blob header promising more is refused before a byte of
#: the body is read.
MAX_NOTE_FILE_BYTES = 25 * 1024 * 1024


def doc_id_for_bytes(data: bytes) -> str:
    """Content-derived document id — the same rule the textbook path uses
    (`ingest/canonical.py`: the first 12 hex of the sha256). Identical bytes
    hash to one document, which is exactly what the backend's citation
    resolver expects (several files may claim one doc id)."""
    return hashlib.sha256(data).hexdigest()[:12]


class _Bucket:
    """One school's note rows, plus indexes rebuilt lazily after a write."""

    def __init__(self) -> None:
        self.ids: list[str] = []
        self.texts: list[str] = []
        self.vectors: list[np.ndarray] = []
        self.sparse: list[dict] = []
        self.chunks: dict = {}           # chunk_id -> Chunk
        self.spans: dict = {}            # span_id -> {"page", "bbox"}
        self.owner: dict = {}            # chunk_id -> note key
        self.dense = None
        self.bm25 = None
        self.spar = None
        self.dirty = True

    def rebuild(self, school: str) -> None:
        if not self.dirty:
            return
        if self.ids:
            self.dense = DenseIndex(dim=1024).build(
                list(self.ids), np.asarray(self.vectors, dtype=np.float32),
                school=school)
            self.bm25 = BM25Index().build(list(self.ids), list(self.texts),
                                          school=school)
            self.spar = SparseIndex().build(list(self.ids), list(self.sparse),
                                            school=school)
        else:
            self.dense = self.bm25 = self.spar = None
        self.dirty = False


class NoteIndex:
    """School-scoped course-note rows + their three retrieval indexes.

    Thread-safe: `rag.index` runs in the transport's executor thread while
    `rag.chat` retrieves on request threads.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    # -- yazma ------------------------------------------------------------
    def replace_note(self, school: str, course_note: str, rows) -> int:
        """Swap one note's rows for `rows` — the note-level unit of update.

        `rows` is `[(Chunk, dense_vector, sparse_dict), ...]`. The previous rows
        of this note are dropped first, so a re-index is idempotent by
        construction (chunk ids are note-scoped; nothing survives to duplicate).
        """
        from src.guard.tenant import require_owner
        sahip = require_owner(school)
        with self._lock:
            bucket = self._buckets.setdefault(sahip, _Bucket())
            self._drop_locked(bucket, course_note)
            for chunk, vector, sparse in rows:
                cid = chunk.chunk_id
                bucket.ids.append(cid)
                bucket.texts.append(chunk.text)
                bucket.vectors.append(np.asarray(vector, dtype=np.float32))
                bucket.sparse.append({str(k): float(v) for k, v in dict(sparse).items()})
                bucket.chunks[cid] = chunk
                bucket.owner[cid] = course_note
                for sid in chunk.span_ids:
                    bucket.spans[sid] = {"page": chunk.page_start,
                                         "bbox": (0.0, 0.0, 0.0, 0.0)}
            bucket.dirty = True
            return len(rows)

    def drop_note(self, school: str, course_note: str) -> int:
        from src.guard.tenant import require_owner
        sahip = require_owner(school)
        with self._lock:
            bucket = self._buckets.get(sahip)
            if bucket is None:
                return 0
            n = self._drop_locked(bucket, course_note)
            bucket.dirty = True
            return n

    @staticmethod
    def _drop_locked(bucket: _Bucket, course_note: str) -> int:
        victims = [cid for cid, owner in bucket.owner.items() if owner == course_note]
        if not victims:
            return 0
        drop = set(victims)
        keep = [i for i, cid in enumerate(bucket.ids) if cid not in drop]
        bucket.ids = [bucket.ids[i] for i in keep]
        bucket.texts = [bucket.texts[i] for i in keep]
        bucket.vectors = [bucket.vectors[i] for i in keep]
        bucket.sparse = [bucket.sparse[i] for i in keep]
        for cid in victims:
            cid_chunk = bucket.chunks.pop(cid, None)
            bucket.owner.pop(cid, None)
            for sid in (getattr(cid_chunk, "span_ids", None) or []):
                bucket.spans.pop(sid, None)
        return len(victims)

    # -- okuma ------------------------------------------------------------
    def retrieve(self, query: str, embedder, *, school: str, top_k: int = 40,
                 rrf_k: int = 60):
        """Rank this school's note rows — `[(chunk_id, rrf_score), ...]`.

        The tenant filter is the store's own (`school=` on every index search):
        another school's notes, and rows with no school stamp, are never
        returned (`guard/tenant.py`).
        """
        if not query or not query.strip() or not school:
            return []
        with self._lock:
            bucket = self._buckets.get(school)
            if bucket is None or not bucket.ids:
                return []
            bucket.rebuild(school)
            dense, bm25, spar = bucket.dense, bucket.bm25, bucket.spar
        sorgu = getattr(embedder, "embed_query", None)
        qv = sorgu(query)[0] if sorgu is not None else embedder.embed([query])[0]
        rankings = [dense.search(qv, top_k, school=school),
                    bm25.search(query, top_k, school=school)]
        if spar is not None:
            qs = embedder.embed_sparse([query])[0]
            rankings.append(spar.search(qs, top_k, school=school))
        return rrf_fuse(rankings, k=rrf_k, top_k=top_k)

    def chunk(self, chunk_id: str):
        with self._lock:
            for bucket in self._buckets.values():
                if chunk_id in bucket.chunks:
                    return bucket.chunks[chunk_id]
        return None

    def span(self, span_id: str):
        with self._lock:
            for bucket in self._buckets.values():
                if span_id in bucket.spans:
                    return bucket.spans[span_id]
        return None

    def stats(self) -> dict:
        with self._lock:
            return {school: len(bucket.ids) for school, bucket in self._buckets.items()
                    if bucket.ids}


_SHARED: NoteIndex | None = None
_SHARED_LOCK = threading.Lock()


def shared_note_index() -> NoteIndex:
    """The process-wide note index.

    `rag.index` (transport thread) and `rag.chat` (request threads) must see the
    same rows, and the service is built per corpus — so the store is a process
    singleton, like `guard/tenant.py`'s rules and the provider configuration.
    """
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = NoteIndex()
        return _SHARED


class NoteAwareChunks(Mapping):
    """`{chunk_id: object}` that falls back to the note index.

    `Generator` holds `chunks_by_id` and `span_meta` — both built once, from a
    corpus that was on disk at build time. Note rows arrive later (and are
    replaced), so lookups consult the live note index first; the base mapping
    answers everything else. Read-only `Mapping` is enough: the pipeline only
    reads (`cid in chunks`, `chunks[cid].text`, `span_meta.get(sid)`).
    """

    def __init__(self, base, lookup) -> None:
        self._base = base
        self._lookup = lookup          # (key) -> value | None

    def __getitem__(self, key):
        found = self._lookup(key)
        if found is not None:
            return found
        return self._base[key]

    def __iter__(self):
        yield from self._base
        # Live rows are not enumerated: the base keys are what a caller
        # iterates for counts/aggregates, and the note rows are already found
        # by id. Enumerating them here would silently change `len()` semantics.

    def __len__(self) -> int:
        return len(self._base)

    def get(self, key, default=None):
        found = self._lookup(key)
        return found if found is not None else self._base.get(key, default)

    def __contains__(self, key) -> bool:
        return self._lookup(key) is not None or key in self._base


def merge_hits(base_hits, extra_hits, top_k: int, *, rrf_k: int = 60):
    """RRF-merge two best-first rank lists — the subject corpus's hits and the
    school's note hits. Ranks (not scores) are what RRF uses, which is exactly
    what two differently-calibrated indexes need."""
    if not extra_hits:
        return base_hits
    if not base_hits:
        return extra_hits[:top_k]
    return rrf_fuse([base_hits, extra_hits], k=rrf_k, top_k=top_k)
