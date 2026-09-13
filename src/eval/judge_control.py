"""#72 / EXP-010 #M3-9 (EVAL-06) — HAKEM NEGATİF KONTROLÜ ve AYIRT ETME GÜCÜ.

ÖLÇÜLEN DURUM: LLM hakemi hiç kalibre edilmedi **ve üretici ile hakem AYNI
MODEL** (self-preference). Skorlar rapora giriyor ama hakemin kötü bir
cevabı kötü bulup bulmadığı hiç sınanmadı.

NEDEN ÖNEMLİ: kalibre edilmemiş hakem, ölçümün tamamını geçersiz kılar.
Her şeye 0,9 veren bir hakem "ürün mükemmel" der; her şeye 0,3 veren bir
hakem gerçek iyileşmeyi gizler. İkisi de aynı ölçüde yanlıştır ve ikisi de
tek yönlü bakışta GÖRÜNMEZ.

BU YÜZDEN İKİ YÖN BİRDEN ÖLÇÜLÜR (EXP-013'te öğrenilen ders):
  - NEGATİF kontrol: kasten bozulmuş cevap → hakem DÜŞÜK vermeli.
  - POZİTİF kontrol: gold cevabın kendisi → hakem YÜKSEK vermeli.
Yalnız negatif ölçmek, "her şeye düşük veren" bozuk bir hakemi TAM PUANLA
geçirirdi.

Hakem GEÇERLİ sayılmaz, ölçülür: `discrimination = mean(pozitif) -
mean(negatif)` ve bunun güven aralığı. Kararı insan verir (#91).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .metrics import bootstrap_ci, mean

# Bozma türleri. Her biri FARKLI bir hakem metriğini hedefler; hepsini tek
# bir bozma türüyle sınamak, hakemin yalnız o boyutta çalıştığını gizlerdi.
CORRUPTIONS = ("fabricated_fact", "negation", "off_topic", "empty", "evasive")

# Bağlamda GEÇMEYEN, doğrulanabilir biçimde uydurma cümleler. Kasten somut
# (tarih/sayı/özel ad) seçildi: belirsiz bir uydurma hakemin "olabilir"
# demesine alan bırakır, somut olan bırakmaz.
FABRICATIONS = (
    "Bu konu ilk kez 1923 yılında Ankara'da bir laboratuvarda kanıtlanmıştır.",
    "Türkiye'de bu süreç yılda tam 47,3 milyon ton madde dönüşümü sağlar.",
    "Bu olayın kaşifi, 1961 Nobel Fizyoloji Ödülü'nü kazanan Dr. Selim Ergün'dür.",
    "Ders kitabının 412. sayfasında bu konunun istisnası açıklanmıştır.",
)

OFF_TOPIC = (
    "Osmanlı Devleti'nin kuruluş tarihi 1299'dur ve kurucusu Osman Bey'dir.",
    "Bir üçgenin iç açıları toplamı 180 derecedir.",
    "Türkçede ünlü uyumu, kelimelerdeki ünlülerin kalınlık-incelik bakımından "
    "uyumlu olmasıdır.",
)

EVASIONS = (
    "Bu sorunun cevabı ders kitabında ayrıntılı olarak anlatılmaktadır.",
    "Konuyu öğretmeninize sormanız daha doğru olur.",
)

NEGATION_PAIRS = (("artar", "azalır"), ("azalır", "artar"),
                  ("vardır", "yoktur"), ("gerekir", "gerekmez"),
                  ("mümkündür", "mümkün değildir"), ("üretir", "tüketir"),
                  ("yüksek", "düşük"), ("hızlanır", "yavaşlar"))


@dataclass
class ControlCase:
    """Hakeme verilecek tek bir sınama vakası.

    `expected`: "high" (pozitif kontrol) | "low" (negatif kontrol).
    `targets`: bu bozmanın DÜŞÜRMESİ beklenen metrikler.
    """
    id: str
    kind: str
    expected: str
    question: str
    answer_text: str
    contexts: list = field(default_factory=list)
    gold_answer: str = ""
    targets: tuple = ()


def _first_sentence(text: str) -> str:
    from ..generate.sentences import split_sentences
    parts = split_sentences(text or "")
    return parts[0] if parts else (text or "")


def _negate(text: str, rng: random.Random) -> str | None:
    """Metindeki bir iddiayı TERSİNE çevirir. Uygun kelime yoksa None —
    zorlama bir bozma, ölçülemeyen bir vaka üretirdi."""
    for src, dst in rng.sample(list(NEGATION_PAIRS), len(NEGATION_PAIRS)):
        if src in text:
            return text.replace(src, dst, 1)
    return None


def build_controls(items, *, n: int = 20, seed: int = 20260913) -> list:
    """Golden item'lardan kontrol vakaları üretir.

    Yalnız `beklenen_davranis == "cevapla"` ve gold cevabı OLAN item'lar
    kullanılır: çekimser kalınması beklenen bir item'da "cevabın kalitesi"
    diye bir şey yoktur.
    """
    rng = random.Random(seed)
    uygun = [i for i in items
             if i.get("beklenen_davranis") == "cevapla"
             and (i.get("gold_cevap") or "").strip()
             and (i.get("soru") or "").strip()]
    rng.shuffle(uygun)

    positives: list[ControlCase] = []
    negatives: list[ControlCase] = []
    # Yarı pozitif / yarı negatif ve negatifler BEŞ bozma türüne EŞİT dağılır.
    # İlk sürümde bozma türü `len(cases) % 5` ile seçiliyordu; pozitif vakalar
    # da aynı listeye eklendiği için sayaç ikişer artıyor ve beş türün yalnız
    # ikisi üretiliyordu. Ölçüm aracının kendi kusuru, ölçtüğü şeyden daha
    # sessizce yanıltır.
    n_pos = n // 2
    per_kind = {k: 0 for k in CORRUPTIONS}
    kota = max(1, (n - n_pos) // len(CORRUPTIONS))

    for item in uygun:
        if len(positives) >= n_pos and len(negatives) >= n - n_pos:
            break
        gold = item["gold_cevap"].strip()
        soru = item["soru"].strip()
        ctx = [gold]
        iid = item.get("id", "?")

        # POZİTİF kontrol: gold cevabın kendisi. Hakem buna DÜŞÜK verirse
        # bütün negatif sonuçları anlamsızdır.
        if len(positives) < n_pos:
            positives.append(ControlCase(
                id=f"{iid}::positive", kind="verbatim_gold", expected="high",
                question=soru, answer_text=gold, contexts=ctx, gold_answer=gold,
                targets=("faithfulness", "groundedness", "answer_relevancy",
                     "answer_correctness")))
            continue

        for tur in CORRUPTIONS:
            if per_kind[tur] >= kota:
                continue
            bozuk, hedef = None, ()
            if tur == "fabricated_fact":
                # Gold'un İÇİNE uydurma bir cümle sokulur: cevabın çoğu doğru,
                # bir cümlesi kaynakta YOK. Gerçek hatalar böyle görünür —
                # baştan sona saçma bir cevabı ayırmak kolaydır, asıl sınav bu.
                bozuk = f"{gold} {rng.choice(FABRICATIONS)}"
                # `faithfulness` bunu KAÇIRIYOR (ölçüldü: 1,000); asıl hedef
                # `groundedness`. İkisi de raporlanır ki fark görünür kalsın.
                hedef = ("faithfulness", "groundedness")
            elif tur == "negation":
                cumle = _first_sentence(gold)
                ters = _negate(cumle, rng)
                if ters:
                    bozuk = gold.replace(cumle, ters, 1)
                    hedef = ("answer_correctness",)
            elif tur == "off_topic":
                bozuk = rng.choice(OFF_TOPIC)
                hedef = ("answer_relevancy", "answer_correctness")
            elif tur == "empty":
                bozuk = ""
                hedef = ("answer_relevancy",)
            elif tur == "evasive":
                bozuk = rng.choice(EVASIONS)
                hedef = ("answer_relevancy",)
            if bozuk is None:                 # uygun bozma yapılamadı
                continue
            per_kind[tur] += 1
            negatives.append(ControlCase(
                id=f"{iid}::{tur}", kind=tur, expected="low", question=soru,
                answer_text=bozuk, contexts=ctx, gold_answer=gold, targets=hedef))
            break

    return (positives + negatives)[:n]


@dataclass
class ControlReport:
    n: int = 0
    positive: dict = field(default_factory=dict)
    negative: dict = field(default_factory=dict)
    discrimination: dict = field(default_factory=dict)
    by_kind: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    cases: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"n": self.n, "positive": self.positive, "negative": self.negative,
                "discrimination": self.discrimination, "by_kind": self.by_kind,
                "errors": self.errors, "cases": self.cases}


METRICS = ("faithfulness", "groundedness", "answer_relevancy",
           "answer_correctness")


def run_controls(judge, cases) -> ControlReport:
    """Kontrol vakalarını hakeme verir ve AYIRT ETME GÜCÜNÜ ölçer.

    Hiçbir yerde "hakem geçti" denmez; ölçüm döndürülür ve kararı insan
    verir (pass-bias yasak).
    """
    rapor = ControlReport(n=len(cases))
    skorlar = {"high": {m: [] for m in METRICS}, "low": {m: [] for m in METRICS}}
    tur_skorlari: dict = {}

    for case in cases:
        try:
            r = judge.evaluate(question=case.question, answer_text=case.answer_text,
                               retrieved_contexts=list(case.contexts),
                               gold_answer=case.gold_answer)
        except Exception as e:                                  # noqa: BLE001
            rapor.errors.append(f"{case.id}: {type(e).__name__}: {e}")
            continue
        if getattr(r, "errors", None):
            rapor.errors.extend(f"{case.id}: {m}" for m in r.errors)

        satir = {"id": case.id, "kind": case.kind, "expected": case.expected,
                 "targets": list(case.targets)}
        for m in METRICS:
            v = getattr(r, m, None)
            satir[m] = v
            if isinstance(v, (int, float)):
                skorlar[case.expected][m].append(float(v))
                # Tür kırılımında YALNIZ hedeflenen metrik anlamlıdır:
                # "off_topic" bir cevap bağlama sadık (faithful) OLABİLİR.
                if case.expected == "low" and m in case.targets:
                    tur_skorlari.setdefault(case.kind, {}).setdefault(m, []).append(float(v))
                elif case.expected == "high":
                    tur_skorlari.setdefault(case.kind, {}).setdefault(m, []).append(float(v))
        rapor.cases.append(satir)

    for etiket, kova in (("positive", "high"), ("negative", "low")):
        hedef = getattr(rapor, etiket)
        for m in METRICS:
            vals = skorlar[kova][m]
            hedef[m] = {"n": len(vals), "mean": mean(vals),
                        "ci": bootstrap_ci(vals) if len(vals) >= 2 else None}

    for m in METRICS:
        p, ng = rapor.positive[m]["mean"], rapor.negative[m]["mean"]
        rapor.discrimination[m] = (None if p is None or ng is None
                                   else round(p - ng, 4))

    rapor.by_kind = {k: {m: {"n": len(v), "mean": mean(v)} for m, v in d.items()}
                     for k, d in tur_skorlari.items()}
    return rapor


def cohen_kappa(a, b) -> float | None:
    """İki etiketleyici arasındaki uyum (şansa göre düzeltilmiş).

    #M3-9 TAM kapısı: insan etiketiyle hakem arasında κ ≥ 0,75. İnsan
    etiketleri gelene kadar (#91) burada yalnız hesap hazır durur.

    κ = (p_o - p_e) / (1 - p_e). Tam uyum ama TEK sınıf varsa p_e = 1 olur
    ve κ tanımsızdır (0/0) — bu durumda None döner; 1,0 döndürmek "mükemmel
    uyum" yanılsaması yaratırdı.
    """
    a, b = list(a), list(b)
    if not a or len(a) != len(b):
        return None
    n = len(a)
    labels = sorted(set(a) | set(b))
    p_o = sum(1 for x, y in zip(a, b) if x == y) / n
    p_e = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    if abs(1.0 - p_e) < 1e-12:
        return None
    return round((p_o - p_e) / (1.0 - p_e), 4)
