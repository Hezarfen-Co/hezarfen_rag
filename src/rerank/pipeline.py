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


# M2-7 (#59, EXP-010/ACC-06) -- CESITLILIK ARTIK TAVAN DEGIL TABAN.
#
# Eski davranis: `per_parent=1` TUM yuvalara uygulaniyordu. Ayni parent'ta iki
# gercek kanit varsa ikincisi -- skoru ne olursa olsun -- eleniyordu.
# Kosulan kanit (4 aday: a1,a2 ayni parent=gold; b1,b2 alakasiz):
#   top_n=2 -> ['a1','b1'], gold kapsama 1/2, recall 0,5
#   top_n=6, 6 farkli parent varken -> ['a1','b1','b2','b3','b4','b5'];
#   ikinci gold span (rerank skoru 0,94, 2. EN IYI) tamamen kayboldu, yerine
#   0,89-0,85 skorlu ALAKASIZ chunk'lar geldi.
# Yayginlik: golden set'te 133 cevaplanabilir item'in 70'i cok-span'li
# (44 item 2-span, 16 item 3-span, 8 item >=4-span) -> kural, istisna degil.
#
# Neden "skora duyarli per_parent" DEGIL: `ranked` skor-azalan sirali oldugu
# icin "ayni parent'tan ikinci chunk, sonraki farkli-parent adayindan yuksek
# skorluysa kabul et" kurali HER ZAMAN dogru cikar (sonraki eleman tanim
# geregi daha dusuk skorlu) -> cesitlilik kisiti tumden islevsizlesir ve tek
# bir parent butun yuvalari doldurabilir. Issue'daki ikinci secenek dogru
# olani: kisiti yalnizca yuvalarin SON kismina uygula.
#
# Yeni davranis iki asamali:
#   1. asama (ilk `top_n - ayrilan` yuva): saf skor sirasi, parent kisiti YOK
#      -> ayni parent'taki ikinci gercek kanit artik hayatta kalir.
#   2. asama (kalan `ayrilan` yuva): yalnizca HENUZ TEMSIL EDILMEMIS parent'lar
#      -> tek bir parent baglami ele gecirip konu cesitliligini oldurmez.
# `ayrilan = round(top_n * diversity_share)`, varsayilan yarisi.
DIVERSITY_SHARE_DEFAULT = float(
    __import__("os").environ.get("RAG_DIVERSITY_SHARE", "0.5"))


def rerank_select(query, hits, chunks_by_id, reranker, *, top_n: int = 10,
                  candidate_n: int = 40, per_parent: int = 1,
                  expand_parents: bool = True,
                  diversity_share: float | None = None):
    """hits: [(chunk_id, _skor)] (RRF çıkışı). chunks_by_id: {id -> Chunk}.
    reranker: .rerank(query, [(id,text)]) → [(id,skor)] olan nesne.

    `diversity_share`: yuvaların ne kadarının **yeni parent'lara ayrıldığı**
    (0 = çeşitlilik kısıtı yok, saf skor; 1 = eski davranış, kısıt her yuvada).
    None → env varsayılanı (`RAG_DIVERSITY_SHARE`, 0.5).
    `per_parent`: 2. aşamada bir parent'tan kaç chunk'a izin verildiği.
    """
    if diversity_share is None:
        diversity_share = DIVERSITY_SHARE_DEFAULT
    diversity_share = min(1.0, max(0.0, diversity_share))
    cand = [(cid, chunks_by_id[cid].text)
            for cid, _ in hits[:candidate_n] if cid in chunks_by_id]
    ranked = reranker.rerank(query, cand)

    serbest = top_n - int(round(top_n * diversity_share))
    if diversity_share < 1.0:
        # EN AZ 2 SERBEST YUVA. Testle bulundu: `top_n=2` + `share=0.5` ile
        # serbest yuva 1'e iniyor ve ikinci gold kanit YINE dusuyordu -- yani
        # denetimin birinci senaryosu (top_n=2 -> recall 0,5) duzelmemis
        # oluyordu. Tek yuva cok-span'li bir cevabi temsil EDEMEZ.
        #
        # `share == 1.0` BU TABANDAN MUAF: o deger "kisit her yuvada" yani
        # ESKI DAVRANIS demektir ve ablation'da eski hali birebir yeniden
        # uretebilmek icin bozulmamali.
        serbest = max(min(2, top_n), serbest)

    selected, parent_count, used = [], {}, set()

    def _al(cid, sc, ch):
        selected.append((cid, sc, ch))
        used.add(cid)
        if ch.parent_id is not None:
            parent_count[ch.parent_id] = parent_count.get(ch.parent_id, 0) + 1

    # 1. aşama — saf skor sırası, parent kısıtı YOK
    for cid, sc in ranked:
        if len(selected) >= serbest:
            break
        _al(cid, sc, chunks_by_id[cid])

    # 2. aşama — yalnız `per_parent`'ı aşmayanlar (yeni parent'lara ayrılmış yuvalar)
    for cid, sc in ranked:
        if len(selected) >= top_n:
            break
        if cid in used:
            continue
        ch = chunks_by_id[cid]
        pid = ch.parent_id
        if pid is not None and parent_count.get(pid, 0) >= per_parent:
            continue
        _al(cid, sc, ch)

    if len(selected) < top_n:                      # fallback: çeşitlilik kısıtını gevşet
        for cid, sc in ranked:
            if cid in used:
                continue
            _al(cid, sc, chunks_by_id[cid])
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
