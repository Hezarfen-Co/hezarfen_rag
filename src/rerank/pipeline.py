"""Faz 1.5 — rerank + çeşitlilik + parent genişletme.

Akış: RRF aday havuzu (top-N) → cross-encoder rerank → çeşitlilik (parent başına
en çok `per_parent` chunk; aşırı-tekrarı eler) → ilk `top_n` (8-12) → her seçilen
child'ı parent bağlamıyla genişlet (üretimde LLM'e daha bütün bağlam). Atıf child
span'ında kalır (parent yalnız bağlam), mimari §0.1: cevap ham leaf span'lara bağlı.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RerankedContext:
    chunk_id: str
    score: float
    text: str
    span_ids: list = field(default_factory=list)
    parent_id: str | None = None
    parent_text: str | None = None        # parent genişletme (bağlam)
    # M2-2 (#54, EXP-010/ACC-03): parent metni prompt'a giriyordu ama parent'in
    # KENDI span'lari tasinmiyordu -- atif/sayfa yalniz child'dan hesaplaniyordu.
    # Model parent'taki bilgiyi kullanip [N] atifladiginda donen sayfa CHILD'in
    # sayfasiydi; kullanici atifa tiklayinca iddiayi o sayfada BULAMIYORDU.
    parent_span_ids: list = field(default_factory=list)


def rerank_select(query, hits, chunks_by_id, reranker, *, top_n: int = 10,
                  candidate_n: int = 40, per_parent: int = 1,
                  expand_parents: bool = True):
    """hits: [(chunk_id, _skor)] (RRF çıkışı). chunks_by_id: {id -> Chunk}.
    reranker: .rerank(query, [(id,text)]) → [(id,skor)] olan nesne."""
    cand = [(cid, chunks_by_id[cid].text)
            for cid, _ in hits[:candidate_n] if cid in chunks_by_id]
    ranked = reranker.rerank(query, cand)

    # çeşitlilik: parent başına en çok `per_parent`; yetersizse kalanlarla doldur
    selected, parent_count, used = [], {}, set()
    for cid, sc in ranked:
        ch = chunks_by_id[cid]
        pid = ch.parent_id
        if pid is not None and parent_count.get(pid, 0) >= per_parent:
            continue
        selected.append((cid, sc, ch)); used.add(cid)
        if pid is not None:
            parent_count[pid] = parent_count.get(pid, 0) + 1
        if len(selected) >= top_n:
            break
    if len(selected) < top_n:                      # fallback: çeşitlilik kısıtını gevşet
        for cid, sc in ranked:
            if cid in used:
                continue
            selected.append((cid, sc, chunks_by_id[cid])); used.add(cid)
            if len(selected) >= top_n:
                break

    results = []
    for cid, sc, ch in selected:
        ptext, pspans = None, []
        if expand_parents and ch.parent_id and ch.parent_id in chunks_by_id:
            parent = chunks_by_id[ch.parent_id]
            ptext = parent.text
            # #54: parent'in span'lari da tasinir ki atif/sayfa DOGRU kaynaktan
            # hesaplanabilsin. child span'lari burada DUSULMEZ -- hangi kismin
            # gercekten "ek baglam" oldugunu Generator karar verir (metni de
            # orada kirpar), boylece bu katman saf veri tasiyici kalir.
            pspans = list(parent.span_ids)
        results.append(RerankedContext(cid, sc, ch.text, list(ch.span_ids),
                                       ch.parent_id, ptext, pspans))
    return results
