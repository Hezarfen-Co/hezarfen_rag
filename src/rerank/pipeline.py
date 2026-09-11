"""Faz 1.5 — rerank + çeşitlilik + parent genişletme.

Akış: RRF aday havuzu (top-N) → cross-encoder rerank → çeşitlilik (parent başına
en çok `per_parent` chunk; aşırı-tekrarı eler) → ilk `top_n` (8-12) → her seçilen
child'ı parent bağlamıyla genişlet (üretimde LLM'e daha bütün bağlam). Atıf child
span'ında kalır (parent yalnız bağlam), mimari §0.1: cevap ham leaf span'lara bağlı.
"""
from __future__ import annotations

import os
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


# M2-7 (#59, EXP-010/ACC-06) -- KISIT YAPISAL DEGIL, ILGILILIK TABANLI.
#
# Eski davranis: `per_parent=1` TUM yuvalara uygulaniyordu. Ayni parent'ta iki
# gercek kanit varsa ikincisi -- skoru ne olursa olsun -- eleniyordu.
# Kosulan kanit (4 aday: a1,a2 ayni parent=gold; b1,b2 alakasiz):
#   top_n=2 -> ['a1','b1'], gold kapsama 1/2
#   top_n=6, 6 farkli parent varken -> ikinci gold span (skor 0,94, 2. EN IYI)
#   tamamen kayboldu, yerine 0,89-0,85 skorlu ALAKASIZ chunk'lar geldi.
# Yayginlik: golden set'te 133 cevaplanabilir item'in 70'i cok-span'li.
#
# GERCEK KITAPLA ABLATION (10-biyoloji, 120 cift-igne sorgusu, top_n=6):
#   diversity_share=1.0 (eski) -> all_evidence_recall 0,000  (!!)
#   diversity_share=0.5        -> 0,242
#   diversity_share=0.0        -> 0,483
# Yani eski kural ayni parent'taki iki kaniti HIC birlikte getirmiyordu.
#
# KARAR (Kadir, 2026-09-12): "birden fazla kanit getirebilir, 2'den de fazla
# olabilir, konuyla ilgiliyse -- ama ILGILI OLMASI LAZIM." Yani dogru olcut
# kac chunk'in ayni parent'tan geldigi DEGIL, ilgili olup olmadigi.
#
# ILGILILIK ESIGI VERIDEN SECILDI (ayni kitap, 23 gercek sorgu, top-40 rerank):
#   tum skorlar : medyan 0,006  p90 0,619   -> dagilim IKI KUTUPLU
#   1. siradaki : medyan 0,848
#   2. siradaki : medyan 0,621
#   10. siradaki: medyan 0,128
# Yani ilgili olan yuksek, alakasiz olan ~0 aliyor. Esik iki parcali:
#   score >= max(RELEVANCE_MIN, tepe_skor * RELEVANCE_REL)
# Goreli parca sart: tepe skor sorguya gore 0,0025 ile 0,9999 arasinda
# degisiyor, sabit esik kolay sorguda cok sey alir, zor sorguda hicbir sey.
# Mutlak parca da sart: goreli esik tek basinaysa cop adaylarin orani
# tepeye gore yuksek gorunebilir.
# (Uretimde `abstain_score=0.30` kapisi zaten tepe skor <0,30 olan sorgulari
#  hic buraya getirmiyor; yani burada tepe >= 0,30 varsayilabilir.)
RELEVANCE_MIN = float(os.environ.get("RAG_RELEVANCE_MIN", "0.05"))
RELEVANCE_REL = float(os.environ.get("RAG_RELEVANCE_REL", "0.10"))
# Cesitlilik artik YALNIZ DOLGU: ilgili aday top_n'i doldurmazsa kalan yuvalar
# yeni parent'lara verilir (bagalam genisligi bedava geliyorsa alinir).
DIVERSITY_SHARE_DEFAULT = float(os.environ.get("RAG_DIVERSITY_SHARE", "0.0"))


def rerank_select(query, hits, chunks_by_id, reranker, *, top_n: int = 10,
                  candidate_n: int = 40, per_parent: int = 1,
                  expand_parents: bool = True,
                  diversity_share: float | None = None,
                  relevance_min: float | None = None,
                  relevance_rel: float | None = None):
    """hits: [(chunk_id, _skor)] (RRF çıkışı). chunks_by_id: {id -> Chunk}.
    reranker: .rerank(query, [(id,text)]) → [(id,skor)] olan nesne.

    Seçim iki aşamalı:
      1. **İlgili** adayların hepsi, skor sırasında, parent kısıtı OLMADAN.
         "İlgili" = `score >= max(relevance_min, tepe * relevance_rel)`.
         Aynı parent'tan 2, 3, 5 chunk gelebilir — konuyla ilgili olduğu
         sürece bu bir kusur değil, çok-span'lı cevabın gereğidir.
      2. Yuva kalırsa **dolgu**: eşiği geçmeyen adaylardan, parent başına en
         çok `per_parent` olacak şekilde (bağlam genişliği bedavaysa alınır).

    `diversity_share > 0` verilirse 1. aşamanın yuva sayısı kısıtlanır; bu
    YALNIZ ablation içindir (`1.0` eski davranışı birebir üretir).
    """
    if diversity_share is None:
        diversity_share = DIVERSITY_SHARE_DEFAULT
    diversity_share = min(1.0, max(0.0, diversity_share))
    r_min = RELEVANCE_MIN if relevance_min is None else relevance_min
    r_rel = RELEVANCE_REL if relevance_rel is None else relevance_rel

    cand = [(cid, chunks_by_id[cid].text)
            for cid, _ in hits[:candidate_n] if cid in chunks_by_id]
    ranked = reranker.rerank(query, cand)
    if not ranked:
        return []

    tepe = max(sc for _, sc in ranked)
    esik = max(r_min, tepe * r_rel)

    selected, parent_count, used = [], {}, set()

    def _al(cid, sc, ch):
        selected.append((cid, sc, ch))
        used.add(cid)
        if ch.parent_id is not None:
            parent_count[ch.parent_id] = parent_count.get(ch.parent_id, 0) + 1

    # 1. aşama — İLGİLİ adaylar, parent kısıtı YOK
    serbest = top_n - int(round(top_n * diversity_share))
    if diversity_share < 1.0:
        serbest = max(min(2, top_n), serbest)
    for cid, sc in ranked:
        if len(selected) >= serbest:
            break
        if sc < esik:
            break                      # sıralı liste: buradan sonrası da ilgisiz
        _al(cid, sc, chunks_by_id[cid])

    # 2. aşama — DOLGU: kalan yuvalar, parent çeşitliliğiyle. Dolgu da MUTLAK
    # ilgililik tabanını geçmek zorunda.
    #
    # `top_n` BİR KOTA DEĞİL, ÜST SINIRDIR. Eski kod yuvaları doldurmak için
    # son çare olarak kısıtı tümden gevşetiyor ve skoru ~0 olan chunk'ları da
    # alıyordu. Bu sadece zarar: bağlamı sulandırır (Lost-in-the-Middle),
    # token maliyetini artırır ve üretici modele "bunlar da kaynak" der.
    # Ölçüldü (aynı kitap, 23 gerçek sorgu): skor dağılımı iki kutuplu —
    # tüm adayların medyanı 0,006, p90'ı 0,619. Yani eşiğin altı gerçekten
    # alakasızdır, "biraz alakalı" değil.
    for cid, sc in ranked:
        if len(selected) >= top_n:
            break
        if cid in used or sc < r_min:
            continue
        ch = chunks_by_id[cid]
        pid = ch.parent_id
        if pid is not None and parent_count.get(pid, 0) >= per_parent:
            continue
        _al(cid, sc, ch)

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
