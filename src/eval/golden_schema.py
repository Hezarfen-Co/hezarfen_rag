"""Golden set şema v2 + doğrulayıcı (#64, EXP-010/EVAL-01+04+10+11).

ÖLÇÜLEN DURUM (v1):
* **27 item `senaryo=null`** (%13,5 etiketsiz) → judge örneklemesi ve kohort
  kırılımı o item'ları göremiyor.
* `hop_sayisi`, `grup_id`, `kabul_edilebilir_sayfalar`, `yasakli_kaynaklar`,
  `beklenen_reason_prefix`, `gorsel_bagimliligi`, `hard_negative_turu`, `risk`,
  `uzman_uyusmasi` alanları **yok** (benchmark.md §1 bunları zorunlu sayıyor).
* Kimya/fizik setlerinde `senaryo` ve dolu `unite` **yok** → o setlerde
  **judge n=0**; yani ölçüm hiç yapılmıyordu.
* `variant` item'ların **22/22'si** bir `direct` item'la aynı kazanımı
  paylaşıyor ama `grup_id` olmadığı için "varyantlar tek gruba alınır" kuralı
  uygulanamıyordu → aynı soru üç kez sayılıp metriği şişiriyordu.

BU MODÜLÜN AMACI: bu hataları **otomatik yakalamak**. Bugün yazılmış olsaydı
EVAL-01 ve EVAL-10 denetime kalmadan çıkardı.

PASS-BIAS YASAK: doğrulayıcı "geçsin diye" gevşetilmez. Bir kural ihlal
ediliyorsa ya veri düzeltilir ya kural açıkça değiştirilir — sessizce
atlanmaz.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field

SCHEMA_VERSION = "v2"

# benchmark.md §2 taksonomisi. `None` GEÇERLİ DEĞİL — v1'deki asıl hata buydu.
SENARYOLAR = frozenset({
    "direct",        # tek kaynaktan doğrudan cevap
    "synthesis",     # birden çok kaynağı birleştirme
    "multi_hop",     # ≥2 ayrı sayfadan zincirleme çıkarım
    "variant",       # aynı kazanımın farklı sorulmuş hâli
    "global",        # kitabın tamamına/bölüme dair özet sorusu
    "figure_table",  # şekil/tablo okumayı gerektiren
    "multi_turn",    # çok-turlu bağlam
    "out_of_scope",  # korpus dışı
    "unanswerable",  # alan içi ama kaynakta cevabı yok
    "ambiguous",     # soru belirsiz
    "adversarial",   # çelişki/yazım hatası/tuzak
    "hard_negative", # yakın ama yanlış kaynağı ayırt etme
    "harmful",       # guard'ın kesmesi beklenen
    "injection",     # prompt injection denemesi
})

BEKLENEN_DAVRANISLAR = frozenset({"cevapla", "cekimser", "reddet"})

# `beklenen_davranis != cevapla` olan item'lar için beklenen reason öneki.
# DIKKAT: bu kumede BOS DIZE OLMAMALI. Ilk surumde "" vardi ve
# `"uydurma".startswith("")` HER ZAMAN True oldugu icin kontrol fiilen hic
# calismiyordu -- tanimsiz her sebep gecerli sayiliyordu. Kendi testim yakaladi.
REASON_ONEKLERI = frozenset({
    "guard_", "insufficient_data", "model_abstained", "ungrounded",
    "out_of_scope", "empty_scope", "role_", "scope_", "llm_unavailable",
    "budget_exceeded", "scope_too_large", "service_warming_up",
})

HARD_NEGATIVE_TURLERI = frozenset({
    "yakin_konu",      # komşu konu, yanlış cevap verir
    "ayni_terim",      # aynı terim farklı bağlamda
    "eski_surum",      # kaynağın eski hâli
    "baska_sinif",     # başka sınıfın aynı konusu
    "baska_ders",      # başka dersin aynı terimi
    "kismi_ortusme",   # sorunun yalnız bir kısmını karşılayan kaynak
})

RISKLER = frozenset({"dusuk", "orta", "yuksek"})

# Hedef dağılım (benchmark.md §1). Tolerans ±%5 puan.
HEDEF_DAGILIM = {
    "figure_table": 0.15,
    "global": 0.10,
    "adversarial": 0.05,
    "hard_negative": 0.125,
    "unanswerable": 0.10,
    "multi_turn": 0.075,
}
DAGILIM_TOLERANS = 0.05


@dataclass
class ValidationIssue:
    item_id: str
    field: str
    message: str

    def __str__(self) -> str:
        return f"[{self.item_id}] {self.field}: {self.message}"


@dataclass
class ValidationReport:
    n_items: int = 0
    errors: list = field(default_factory=list)      # şema ihlali — set GEÇERSİZ
    warnings: list = field(default_factory=list)    # dağılım/kalite uyarısı
    distribution: dict = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return (f"{self.n_items} item · {len(self.errors)} hata · "
                f"{len(self.warnings)} uyarı")


def _hata(rapor, item, alan, mesaj):
    rapor.errors.append(ValidationIssue(str(item.get("id", "?")), alan, mesaj))


def validate_item(item: dict, rapor: ValidationReport) -> None:
    """Tek item'ı v2 şemasına göre doğrular."""
    iid = str(item.get("id", "?"))
    if not item.get("id"):
        _hata(rapor, item, "id", "zorunlu")

    senaryo = item.get("senaryo")
    if not senaryo:
        # v1'in asıl hatası: 27 item etiketsizdi ve judge örneklemesi onları
        # hiç görmüyordu.
        _hata(rapor, item, "senaryo", "zorunlu (v1'de 27 item etiketsizdi)")
    elif senaryo not in SENARYOLAR:
        _hata(rapor, item, "senaryo", f"taksonomi dışı: {senaryo}")

    davranis = item.get("beklenen_davranis")
    if davranis not in BEKLENEN_DAVRANISLAR:
        _hata(rapor, item, "beklenen_davranis", f"geçersiz: {davranis}")

    if not (item.get("unite") or "").strip():
        _hata(rapor, item, "unite", "zorunlu (kimya/fizik setlerinde boştu → judge n=0)")

    spanlar = item.get("gold_kaynak_spanlar") or []
    sayfalar = item.get("gold_sayfalar") or []
    if davranis == "cevapla":
        if not spanlar:
            _hata(rapor, item, "gold_kaynak_spanlar",
                  "`cevapla` item'ı gold kanıtsız olamaz")
        if not sayfalar:
            _hata(rapor, item, "gold_sayfalar", "`cevapla` item'ı gold sayfasız olamaz")
        if not (item.get("gold_cevap") or "").strip():
            _hata(rapor, item, "gold_cevap", "`cevapla` item'ı gold cevapsız olamaz")
    else:
        onek = item.get("beklenen_reason_prefix")
        if onek is None:
            _hata(rapor, item, "beklenen_reason_prefix",
                  "`cevapla` olmayan item beklenen reason'ı bildirmeli")
        elif not str(onek).strip():
            _hata(rapor, item, "beklenen_reason_prefix", "bos olamaz")
        elif not any(str(onek).startswith(p) for p in REASON_ONEKLERI):
            _hata(rapor, item, "beklenen_reason_prefix", f"tanınmayan: {onek}")

    hop = item.get("hop_sayisi")
    if hop is None:
        _hata(rapor, item, "hop_sayisi", "zorunlu")
    elif not isinstance(hop, int) or hop < 0:
        _hata(rapor, item, "hop_sayisi", f"negatif olmayan tamsayı olmalı: {hop}")
    elif senaryo == "multi_hop":
        if hop < 2:
            _hata(rapor, item, "hop_sayisi", "multi_hop için ≥2 olmalı")
        if len(set(sayfalar)) < 2:
            _hata(rapor, item, "gold_sayfalar",
                  "multi_hop item'ı ≥2 AYRI gold sayfa taşımalı")

    if senaryo == "hard_negative":
        tur = item.get("hard_negative_turu")
        if tur not in HARD_NEGATIVE_TURLERI:
            _hata(rapor, item, "hard_negative_turu", f"geçersiz: {tur}")

    risk = item.get("risk")
    if risk not in RISKLER:
        _hata(rapor, item, "risk", f"geçersiz: {risk}")

    gorsel = item.get("gorsel_bagimliligi")
    if not isinstance(gorsel, bool):
        _hata(rapor, item, "gorsel_bagimliligi", "bool olmalı")
    elif gorsel and senaryo != "figure_table":
        rapor.warnings.append(ValidationIssue(
            iid, "gorsel_bagimliligi",
            "görsele bağımlı ama senaryo figure_table değil"))

    for alan in ("kabul_edilebilir_sayfalar", "yasakli_kaynaklar"):
        d = item.get(alan)
        if d is None or not isinstance(d, list):
            _hata(rapor, item, alan, "liste olmalı (boş olabilir)")

    uyusma = item.get("uzman_uyusmasi")
    if uyusma is not None and not (isinstance(uyusma, (int, float))
                                   and 0.0 <= uyusma <= 1.0):
        _hata(rapor, item, "uzman_uyusmasi", "0..1 arası ya da None olmalı")


def validate(items: list, *, check_distribution: bool = True) -> ValidationReport:
    """Golden set'i doğrular. `errors` doluysa set GEÇERSİZDİR."""
    rapor = ValidationReport(n_items=len(items))
    if not items:
        rapor.errors.append(ValidationIssue("-", "items", "golden set bos"))
        return rapor

    gorulen_id = set()
    for item in items:
        iid = str(item.get("id", "?"))
        if iid in gorulen_id:
            _hata(rapor, item, "id", "tekrar eden id")
        gorulen_id.add(iid)
        validate_item(item, rapor)

    # grup_id: varyantlar tek gruba alınmalı, yoksa aynı soru birden çok kez
    # sayılıp metriği şişirir (v1'de 22/22 varyant gruplanmamıştı).
    gruplar = collections.defaultdict(list)
    for item in items:
        gid = item.get("grup_id")
        if gid:
            gruplar[gid].append(item)
    for item in items:
        if item.get("senaryo") == "variant" and not item.get("grup_id"):
            _hata(rapor, item, "grup_id",
                  "variant item grup_id taşımalı (v1'de 22/22 gruplanmamıştı)")
    for gid, grup in gruplar.items():
        kazanimlar = {i.get("kazanim_kod") for i in grup}
        if len(kazanimlar) > 1:
            rapor.warnings.append(ValidationIssue(
                gid, "grup_id", f"grup birden çok kazanım içeriyor: {kazanimlar}"))

    sayac = collections.Counter(i.get("senaryo") for i in items)
    rapor.distribution = {k: round(v / len(items), 4) for k, v in sayac.items()}

    if check_distribution:
        for senaryo, hedef in HEDEF_DAGILIM.items():
            oran = rapor.distribution.get(senaryo, 0.0)
            if abs(oran - hedef) > DAGILIM_TOLERANS:
                rapor.warnings.append(ValidationIssue(
                    "-", "dagilim",
                    f"{senaryo}: %{oran*100:.1f} (hedef %{hedef*100:.1f} ±%5)"))
    return rapor


def upgrade_item(item: dict) -> dict:
    """v1 item'ını v2 şemasına taşır — EKSİK ALANLARI UYDURMADAN.

    Çıkarılabilen alanlar doldurulur (`hop_sayisi` gold sayfa sayısından,
    `senaryo` kategoriden); çıkarılamayanlar **None kalır ve doğrulayıcı
    bunları hata olarak bildirir**. Amaç sessizce "geçerli" bir set üretmek
    değil, neyin elle doldurulması gerektiğini göstermek.
    """
    yeni = dict(item)
    yeni.setdefault("schema_version", SCHEMA_VERSION)

    if not yeni.get("senaryo"):
        kategori = (yeni.get("kategori") or "").lower()
        esleme = {"edge_kapsam_disi": "out_of_scope", "edge_zararli": "harmful",
                  "edge_belirsiz": "ambiguous", "edge_injection": "injection",
                  "multi_turn": "multi_turn"}
        yeni["senaryo"] = esleme.get(kategori)      # bilinmiyorsa None KALIR

    sayfalar = yeni.get("gold_sayfalar") or []
    if yeni.get("hop_sayisi") is None:
        yeni["hop_sayisi"] = len(set(sayfalar)) if sayfalar else 0

    davranis = yeni.get("beklenen_davranis")
    if davranis != "cevapla" and yeni.get("beklenen_reason_prefix") is None:
        varsayilan = {"harmful": "guard_", "out_of_scope": "insufficient_data",
                      "injection": "guard_", "unanswerable": "insufficient_data",
                      "ambiguous": "insufficient_data"}
        yeni["beklenen_reason_prefix"] = varsayilan.get(yeni.get("senaryo"))

    yeni.setdefault("kabul_edilebilir_sayfalar", [])
    yeni.setdefault("yasakli_kaynaklar", [])
    yeni.setdefault("gorsel_bagimliligi", False)
    yeni.setdefault("hard_negative_turu", None)
    yeni.setdefault("risk", "orta")
    yeni.setdefault("uzman_uyusmasi", None)
    yeni.setdefault("grup_id", None)
    return yeni


# --- DEV / DONDURULMUS AYRIMI (#71, EXP-010) --------------------------------
#
# NEDEN: esik ayarlamak (abstain_score, top_n, relevance_min...) golden set
# uzerinde yapiliyorsa, o set artik BAGIMSIZ bir olcum degildir -- ayarladigin
# seyle olcuyorsun. Buna test kirlenmesi denir ve kapi degerlerini SISTEMATIK
# olarak iyimser yapar.
#
# Kural: ayar `dev` uzerinde yapilir, KAPI `frozen` uzerinde olculur. Bolme
# deterministiktir (item id hash'i) -- yeniden bolerek "daha iyi" bir ayrim
# aramak da bir kirlenme bicimidir.
#
# TABAKALI: her senaryo kendi icinde bolunur; yoksa nadir kategoriler (ornegin
# adversarial, n=5) tek tarafa dusup digerinde n=0 birakir ve o tarafta o
# kategori hic olculemez.

FROZEN_RATIO = 0.5


def split_dev_frozen(items: list, *, frozen_ratio: float = FROZEN_RATIO,
                     salt: str = "hezarfen-v2") -> tuple[list, list]:
    """(dev, frozen) — deterministik, tabakalı bölme.

    `salt` degistirilirse bolme degisir; bu BILINCLI bir karardir ve yeni bir
    golden SURUMU gerektirir (eski olcumler karsilastirilamaz hale gelir).
    """
    import hashlib
    dev, frozen = [], []
    gruplar = collections.defaultdict(list)
    for item in items:
        gruplar[item.get("senaryo") or "?"].append(item)
    for senaryo, grup in sorted(gruplar.items()):
        # id hash'ine gore sirala -> deterministik ama icerikten bagimsiz
        sirali = sorted(grup, key=lambda i: hashlib.sha256(
            f"{salt}|{i.get('id')}".encode("utf-8")).hexdigest())
        n_frozen = round(len(sirali) * frozen_ratio)
        frozen.extend(sirali[:n_frozen])
        dev.extend(sirali[n_frozen:])
    return dev, frozen


def split_report(items: list, **kw) -> dict:
    """Bölmenin her iki tarafta da her kategoriyi taşıdığını gösterir."""
    dev, frozen = split_dev_frozen(items, **kw)
    d_c = collections.Counter(i.get("senaryo") for i in dev)
    f_c = collections.Counter(i.get("senaryo") for i in frozen)
    senaryolar = sorted(set(d_c) | set(f_c))
    return {"n_dev": len(dev), "n_frozen": len(frozen),
            "per_scenario": {s: {"dev": d_c.get(s, 0), "frozen": f_c.get(s, 0)}
                             for s in senaryolar},
            "empty_side": [s for s in senaryolar
                           if d_c.get(s, 0) == 0 or f_c.get(s, 0) == 0]}
