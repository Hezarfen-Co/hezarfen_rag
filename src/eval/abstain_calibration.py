"""#60 — ÇEKİMSERLİK EŞİĞİNİN KALİBRASYONU.

ÖLÇÜLEN DURUM: `Generator(abstain_score=0.30)` — bu sayı **hiç kalibre
edilmedi**. Kodda sabit bir varsayılan olarak duruyor ve ürünün en görünür
davranışını tek başına belirliyor: tepe rerank skoru eşiğin altındaysa LLM
HİÇ ÇAĞRILMAZ ve öğrenci "kaynaklarda bulamadım" cevabı alır.

Eşik İKİ YÖNDE de yanlış olabilir ve iki yanlışın bedeli farklıdır:

  ÇOK YÜKSEK → cevabı kitapta OLAN soruya "bulamadım" denir.
               Öğrenci ürünü aptal bulur ve bir daha açmaz.
  ÇOK DÜŞÜK  → cevabı kitapta OLMAYAN soruya cevap üretilmeye çalışılır.
               Üretici zayıf kanıtla uydurmaya daha yatkındır; okul
               ortamında yanlış bilgi öğretmek en ağır hatadır.

Tek yönü ölçmek eşiği belirleyemez (EXP-013'ün dersi). Bu modül İKİ YÖNÜ
birden ölçer ve **eşiği seçmez** — ödünleşim eğrisini çıkarır.

YÖNTEM: her item için guard + retrieval + rerank koşulur ve TEPE SKOR
kaydedilir. LLM çağrılmaz (eşik zaten LLM'den ÖNCE karar verir), yani koşum
$0. Sonra eşik offline süpürülür: tek koşumdan bütün eşikler ölçülür.

DEV/FROZEN: ayar YALNIZ dev yarısında yapılır, sonuç frozen yarısında
raporlanır (#M3-8/EVAL-11). Aynı set üzerinde hem seçip hem raporlamak
"genelleme" değil "uyum" ölçer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .metrics import wilson_ci

# Eşiğin KARAR VERDİĞİ senaryolar. Guard'ın yakaladıkları (`harmful`,
# `injection`) buraya girmez: onlar retrieval'a hiç ulaşmaz ve eşikten
# bağımsız reddedilir. Onları saymak eşiği olduğundan iyi gösterirdi.
ANSWERABLE = frozenset({"direct", "synthesis", "multi_hop", "figure_table",
                        "global", "variant", "multi_turn"})
UNANSWERABLE = frozenset({"unanswerable", "out_of_scope", "hard_negative"})
GUARD_OWNED = frozenset({"harmful", "injection"})


@dataclass
class ItemScore:
    id: str
    senaryo: str
    expected: str            # "cevapla" | "cekimser"
    top_score: float | None  # None = hiç bağlam gelmedi (eşikten bağımsız red)
    guard_blocked: bool = False


@dataclass
class ThresholdPoint:
    threshold: float
    n_answerable: int = 0
    false_abstentions: int = 0
    n_unanswerable: int = 0
    false_answers: int = 0

    @property
    def false_abstention_rate(self) -> float | None:
        return (self.false_abstentions / self.n_answerable
                if self.n_answerable else None)

    @property
    def false_answer_rate(self) -> float | None:
        return (self.false_answers / self.n_unanswerable
                if self.n_unanswerable else None)

    def to_dict(self) -> dict:
        fa, fc = self.false_abstention_rate, self.false_answer_rate
        return {
            "threshold": round(self.threshold, 4),
            "n_answerable": self.n_answerable,
            "false_abstentions": self.false_abstentions,
            "false_abstention_rate": None if fa is None else round(fa, 4),
            "false_abstention_ci": wilson_ci(self.false_abstentions,
                                             self.n_answerable),
            "n_unanswerable": self.n_unanswerable,
            "false_answers": self.false_answers,
            "false_answer_rate": None if fc is None else round(fc, 4),
            "false_answer_ci": wilson_ci(self.false_answers, self.n_unanswerable),
        }


def collect_scores(generator, items, *, on_progress=None) -> list:
    """Her item için tepe rerank skorunu ölçer. LLM ÇAĞIRMAZ.

    Guard'ın reddettiği item'lar işaretlenir ve eşik hesabına KATILMAZ.
    """
    out: list[ItemScore] = []
    for i, item in enumerate(items, 1):
        senaryo = item.get("senaryo") or "?"
        beklenen = item.get("beklenen_davranis") or ""
        soru = (item.get("soru") or "").strip()
        skor, bloklu = None, False
        if soru:
            # Guard'ın YALNIZ regex katmanı koşulur. LLM sınıflandırıcı bu
            # ölçüm için gereksiz bir maliyettir: eşik kalibrasyonunda tek
            # ihtiyacımız, guard'ın zaten reddettiği item'ları hesabın DIŞINDA
            # tutmak. Onları saymak eşiği olduğundan iyi gösterirdi.
            from ..guard.input_guard import check_input
            if check_input(soru).action == "refuse" or senaryo in GUARD_OWNED:
                bloklu = True
            else:
                skor = _top_score(generator, soru)
        out.append(ItemScore(id=item.get("id", "?"), senaryo=senaryo,
                             expected=beklenen, top_score=skor,
                             guard_blocked=bloklu))
        if on_progress:
            on_progress(i, len(items), out[-1])
    return out


def _top_score(generator, query: str) -> float | None:
    """Üretimdeki AYNI yoldan tepe skoru alır (retrieve + rerank_select).

    Eşik kontrolü `contexts[0].score` üzerinde yapılır; burada da o değer
    okunur. Ayrı bir yol kullanmak, ölçtüğümüz şeyin ürünün kararı olmaması
    demek olurdu.
    """
    from ..rerank.pipeline import rerank_select
    hits = generator.retriever.retrieve(query, top_k=40)
    contexts = rerank_select(query, hits, generator.chunks_by_id,
                             generator.reranker, top_n=6, candidate_n=40)
    return float(contexts[0].score) if contexts else None


def sweep(scores, *, start: float = 0.0, stop: float = 1.0,
          step: float = 0.01) -> list:
    """Eşik ızgarasını süpürür. Tek koşumdan bütün eşikler ölçülür."""
    cevaplanabilir = [s for s in scores
                      if not s.guard_blocked and s.expected == "cevapla"
                      and s.senaryo in ANSWERABLE]
    cevapsiz = [s for s in scores
                if not s.guard_blocked and s.senaryo in UNANSWERABLE]
    noktalar = []
    esik = start
    while esik <= stop + 1e-9:
        p = ThresholdPoint(threshold=round(esik, 4),
                           n_answerable=len(cevaplanabilir),
                           n_unanswerable=len(cevapsiz))
        # Bağlam hiç gelmediyse (top_score None) eşikten BAĞIMSIZ çekimser.
        p.false_abstentions = sum(
            1 for s in cevaplanabilir
            if s.top_score is None or s.top_score < esik)
        p.false_answers = sum(
            1 for s in cevapsiz
            if s.top_score is not None and s.top_score >= esik)
        noktalar.append(p)
        esik += step
    return noktalar


@dataclass
class CalibrationReport:
    points: list = field(default_factory=list)
    scores: list = field(default_factory=list)
    by_scenario: dict = field(default_factory=dict)
    guard_blocked: int = 0
    no_context: int = 0

    def to_dict(self) -> dict:
        return {
            "points": [p.to_dict() for p in self.points],
            "by_scenario": self.by_scenario,
            "guard_blocked": self.guard_blocked,
            "no_context": self.no_context,
            "scores": [{"id": s.id, "senaryo": s.senaryo,
                        "expected": s.expected, "top_score": s.top_score,
                        "guard_blocked": s.guard_blocked} for s in self.scores],
        }


def report(scores, **sweep_kw) -> CalibrationReport:
    import statistics
    r = CalibrationReport(points=sweep(scores, **sweep_kw), scores=list(scores))
    r.guard_blocked = sum(1 for s in scores if s.guard_blocked)
    r.no_context = sum(1 for s in scores
                       if not s.guard_blocked and s.top_score is None)
    gruplar: dict = {}
    for s in scores:
        if s.guard_blocked or s.top_score is None:
            continue
        gruplar.setdefault(s.senaryo, []).append(s.top_score)
    r.by_scenario = {
        k: {"n": len(v), "min": round(min(v), 4), "max": round(max(v), 4),
            "median": round(statistics.median(v), 4),
            "p10": round(sorted(v)[max(0, int(len(v) * 0.10) - 1)], 4)}
        for k, v in sorted(gruplar.items())}
    return r


def n_needed_to_separate(p_a: float, p_b: float, *, z: float = 1.96) -> int:
    """İki oranı %95 güvenle ayırt etmek için gereken (grup başına) n.

    Kalibrasyonun asıl çıktısı bir eşik DEĞİL, bu sayı oldu: n=26 cevapsız
    item ile 0,115 ile 0,038 arasındaki fark ölçülemez (GA'lar tamamen
    örtüşüyor). Eşik seçmeden önce set büyütülmeli.

    İki oranlı karşılaştırma için standart yaklaşım (normal yaklaşımı):
    n = (z·√(2·p̄·(1−p̄)) + z·√(p_a(1−p_a) + p_b(1−p_b)))² / (p_a − p_b)²
    """
    import math
    fark = abs(p_a - p_b)
    if fark < 1e-9:
        return -1                      # ayırt edilecek fark yok
    ort = (p_a + p_b) / 2.0
    pay = (z * math.sqrt(2 * ort * (1 - ort))
           + z * math.sqrt(p_a * (1 - p_a) + p_b * (1 - p_b))) ** 2
    return int(math.ceil(pay / (fark ** 2)))


def candidates(points, *, max_false_abstention: float = 0.05) -> dict:
    """Karar için ADAY işletme noktaları. SEÇİM YAPMAZ.

    Üç farklı önceliğin her biri farklı bir eşik verir; hangisinin doğru
    olduğu bir ÜRÜN kararıdır, bir hesap değil.
    """
    gecerli = [p for p in points
               if p.false_abstention_rate is not None
               and p.false_answer_rate is not None]
    if not gecerli:
        return {}

    def _en_iyi(secilenler, anahtar):
        return min(secilenler, key=anahtar) if secilenler else None

    # (a) Yanlış cevabı en aza indir, yanlış çekimserliğe tavan koy.
    kisitli = [p for p in gecerli
               if p.false_abstention_rate <= max_false_abstention]
    a = _en_iyi(kisitli, lambda p: (p.false_answer_rate, -p.threshold))
    # (b) İki hatanın TOPLAMI en küçük (ikisine eşit ağırlık).
    b = _en_iyi(gecerli, lambda p: (p.false_abstention_rate
                                    + p.false_answer_rate, p.threshold))
    # (c) Hiç yanlış çekimserlik olmasın (öğrenci deneyimi öncelikli).
    sifir = [p for p in gecerli if p.false_abstentions == 0]
    c = _en_iyi(sifir, lambda p: (p.false_answer_rate, -p.threshold))
    return {ad: (None if p is None else p.to_dict())
            for ad, p in (("min_false_answer_under_cap", a),
                          ("min_total_error", b),
                          ("zero_false_abstention", c))}
