"""EBA (ogmmateryal) catalog çözümleyici — SPA bundle'ından materyal envanteri.

NEDEN YENİDEN YAZILDI (2026-09-12): `eba_dl/` altındaki eski indiriciler
sunucu-render HTML ayrıştırıyordu. Site **SPA'ya dönüştü**: `konu-ozetleri?...`
artık 924 baytlık boş bir kabuk döndürüyor, listeler JS bundle'ının içinde.
Ölçüldü: eski akış "0 items" veriyor, yani indiriciler sessizce hiçbir şey
getirmiyor.

Yeni yol: bundle'daki nesne dizileri ayrıştırılır. Bundle'da `pdfUrl` taşıyan
8129 nesne var; bunların 7461'i `grade` + `lesson`, 7040'ı **`outcome`
(kazanım metni + kodu)** taşıyor.

MÜFREDAT AYRIMI — #94'ÜN CEVABI: catalog `grade` alanında iki ayrı etiket
kullanıyor: `"9"` (yürürlükteki müfredat) ve `"9. Sınıf (2017-23 Müfredatı)"`.
Yani **EBA'nın kendisi eski ve yeni müfredatı ayırıyor**. Elimizdeki
`kazanimlar.json` 2017-23 kodlamasındaydı (`10.1.1.2 Mitozu açıklar`), kitap
ise yeni müfredattan (tema tabanlı) — bu yüzden örtüşmüyorlardı. Katalog
sayesinde artık hangi materyalin hangi müfredata ait olduğu **veriden**
okunabiliyor, tahminle değil.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, asdict

BASE = "https://ogmmateryal.eba.gov.tr"
# Bundle adı sürüm aldığı için sabitlenemez; ana sayfadan okunur.
_BUNDLE_RE = re.compile(r'src="(/assets/index-[^"]+\.js)"')
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# `grade` etiketindeki müfredat işareti
_OLD_CURRICULUM = re.compile(r"2017\s*-\s*23")
_GRADE_RE = re.compile(r"(\d{1,2})")

# Ders adı -> korpus slug'ı (korpustaki klasör adlarıyla birebir)
_SUBJECT_SLUG = {
    "biyoloji": "biyoloji", "fizik": "fizik", "kimya": "kimya",
    "matematik": "matematik", "geometri": "geometri", "cografya": "cografya",
    "felsefe": "felsefe", "tarih": "tarih", "psikoloji": "psikoloji",
    "sosyoloji": "sosyoloji", "mantik": "mantik",
    "turk dili ve edebiyati": "edebiyat", "edebiyat": "edebiyat",
    "ingilizce": "ingilizce", "almanca": "almanca", "fransizca": "fransizca",
    "arapca": "arapca", "din kulturu ve ahlak bilgisi": "din-kulturu",
    "din kulturu": "din-kulturu", "saglik bilgisi": "saglik",
    "gorsel sanatlar": "gorsel-sanatlar", "muzik": "muzik",
    "beden egitimi": "beden", "bilisim teknolojileri": "bilisim",
    "cevre egitimi": "cevre", "t.c. inkilap tarihi ve ataturkculuk": "inkilap",
}


def fold(metin: str) -> str:
    """Türkçe-duyarlı karşılaştırma biçimi (İ/ı katlaması + aksan atma)."""
    if not metin:
        return ""
    m = metin.replace("İ", "i").replace("I", "ı").replace("ı", "i").lower()
    m = unicodedata.normalize("NFKD", m)
    m = "".join(c for c in m if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", m).strip()


def subject_slug(ad: str | None) -> str | None:
    """Katalog ders adı → korpus slug'ı. Tanınmazsa **None** (uydurma yok)."""
    if not ad:
        return None
    k = fold(ad)
    if k in _SUBJECT_SLUG:
        return _SUBJECT_SLUG[k]
    # "İngilizce (Beceri Temelli)" gibi parantezli varyantlar
    yalin = fold(re.sub(r"\(.*?\)", "", ad))
    return _SUBJECT_SLUG.get(yalin)


@dataclass
class Material:
    """Kataloğun bir satırı."""
    sinif: str | None            # "9".."12"; çözülemezse None
    mufredat: str                # "guncel" | "2017-23" | "bilinmiyor"
    ders: str | None             # korpus slug'ı
    ders_adi: str                # kataloğun yazdığı ham ad
    unite: str | None
    kazanim: str | None          # "11.1.1.1.- Sinir sisteminin ..."
    kazanim_kodu: str | None     # "11.1.1.1"
    baslik: str | None
    pdf_url: str

    def to_dict(self) -> dict:
        return asdict(self)


_CODE_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,3}){1,4})")


def _objective_code(outcome: str | None) -> str | None:
    if not outcome:
        return None
    m = _CODE_RE.match(outcome)
    return m.group(1) if m else None


def grade_and_curriculum(grade: str | None) -> tuple[str | None, str]:
    """`grade` etiketini (sınıf, müfredat) ikilisine çevirir.

    `"9"` → ("9", "guncel") · `"9. Sınıf (2017-23 Müfredatı)"` → ("9", "2017-23")
    `"Seçmeli"`, `"Hepsi"` → (None, "bilinmiyor") — bunlar sınıf DEĞİL.
    """
    if not grade:
        return None, "bilinmiyor"
    mufredat = "2017-23" if _OLD_CURRICULUM.search(grade) else "guncel"
    m = _GRADE_RE.search(grade)
    if not m:
        return None, "bilinmiyor"
    n = int(m.group(1))
    if not 5 <= n <= 12:
        return None, "bilinmiyor"
    return str(n), mufredat


def _js_string(ham: str) -> str:
    """JS dizesi → Python dizesi.

    `bytes.decode("unicode_escape")` KULLANILMAZ: latin-1 varsayar ve UTF-8
    Türkçe karakterleri bozar ("Sınıf" → "SÄ±nÄ±f"; ilk denemede bu oldu).
    JSON çözücü hem `\\uXXXX` hem de kaçışları doğru işler.
    """
    try:
        return json.loads('"' + ham + '"')
    except json.JSONDecodeError:
        return ham


def _field(obj: str, ad: str) -> str | None:
    m = re.search(ad + r'\s*:\s*"((?:[^"\\]|\\.)*)"', obj)
    return _js_string(m.group(1)) if m else None


def _pdf_objects(js: str):
    """`pdfUrl` içeren `{...}` nesnelerini dengeli parantezle keser.

    Regex ile tek hamlede kesmek güvenilmez (iç içe nesneler ve kaçışlı
    tırnaklar var); bu yüzden açılış/kapanış sayılır.
    """
    for m in re.finditer(r'pdfUrl\s*:', js):
        derinlik, bas = 0, None
        for i in range(m.start(), max(0, m.start() - 3000), -1):
            if js[i] == "}":
                derinlik += 1
            elif js[i] == "{":
                if derinlik == 0:
                    bas = i
                    break
                derinlik -= 1
        if bas is None:
            continue
        derinlik = 0
        for j in range(bas, min(len(js), bas + 4000)):
            if js[j] == "{":
                derinlik += 1
            elif js[j] == "}":
                derinlik -= 1
                if derinlik == 0:
                    yield js[bas:j + 1]
                    break


def parse_bundle(js: str) -> list[Material]:
    """Bundle metninden materyal listesi. Ağ erişimi YOK (test edilebilir)."""
    out: list[Material] = []
    for obj in _pdf_objects(js):
        pdf = _field(obj, "pdfUrl")
        if not pdf or not pdf.startswith("http"):
            continue
        grade = _field(obj, "grade")
        ders_adi = _field(obj, "lesson") or ""
        sinif, mufredat = grade_and_curriculum(grade)
        outcome = _field(obj, "outcome")
        out.append(Material(
            sinif=sinif, mufredat=mufredat, ders=subject_slug(ders_adi),
            ders_adi=ders_adi, unite=_field(obj, "unit"), kazanim=outcome,
            kazanim_kodu=_objective_code(outcome), baslik=_field(obj, "title"),
            pdf_url=pdf))
    return out


def fetch_bundle(oturum=None, *, timeout: float = 60.0) -> str:
    """Ana sayfadan bundle adresini okuyup içeriğini getirir."""
    import requests
    s = oturum or requests.Session()
    s.headers.setdefault("User-Agent", _UA)
    ana = s.get(BASE, timeout=timeout)
    ana.raise_for_status()
    m = _BUNDLE_RE.search(ana.text)
    if not m:
        raise RuntimeError("bundle adresi bulunamadi (sayfa yapisi degismis olabilir)")
    r = s.get(BASE + m.group(1), timeout=timeout)
    r.raise_for_status()
    return r.text


def catalog(oturum=None) -> list[Material]:
    return parse_bundle(fetch_bundle(oturum))


def summary(materyaller: list[Material]) -> dict:
    """Envanter özeti — indirmeden önce ne geleceğini görmek için."""
    import collections
    sayac = collections.Counter()
    for m in materyaller:
        sayac[(m.mufredat, m.sinif, m.ders)] += 1
    return {
        "toplam": len(materyaller),
        "benzersiz_pdf": len({m.pdf_url for m in materyaller}),
        "kazanimli": sum(1 for m in materyaller if m.kazanim_kodu),
        "sinifi_cozulen": sum(1 for m in materyaller if m.sinif),
        "dersi_cozulen": sum(1 for m in materyaller if m.ders),
        "guncel_mufredat": sum(1 for m in materyaller if m.mufredat == "guncel"),
        "eski_mufredat": sum(1 for m in materyaller if m.mufredat == "2017-23"),
        "kirilim": {f"{a}/{b}/{c}": n for (a, b, c), n in sorted(sayac.items(),
                                                                key=lambda x: -x[1])},
    }


# --------------------------------------------------------------- kazanımlar

def objectives(materials: list[Material], *, curriculum: str = "guncel") -> dict:
    """Katalogdan sınıf/ders başına **kazanım listesi** çıkarır.

    Döner: `{(sinif, ders): [{"kod","metin","unite","mufredat"}, ...]}`

    NEDEN GEREKLİ (#94): `data/.../kazanimlar.json` dosyaları **2017-23
    müfredatının** kodlamasındaydı (`10.1.1.2 Mitozu açıklar`), ders kitapları
    ise yeni müfredattan (tema tabanlı). Ölçüldü: 10. sınıf biyoloji kitabında
    "mitoz" **0 kez** geçiyor. Kapsanmayan bir kazanımdan golden set item'ı ya
    da öğrenci notu üretmek, ürün doğru davranıp çekimser kaldığında bunu bir
    RAG başarısızlığı gibi gösterir — ölçüm böyle zehirlenir.

    Katalog bu ayrımı KENDİSİ yapıyor: `grade` alanı `"9"` (yürürlükteki) ile
    `"9. Sınıf (2017-23 Müfredatı)"` etiketlerini ayrı tutuyor. Yani hangi
    kazanımın hangi müfredattan olduğu artık **veriden** okunur, tahminden değil.
    """
    out: dict[tuple[str, str], dict[str, dict]] = {}
    for m in materials:
        if not (m.sinif and m.ders and m.kazanim_kodu):
            continue
        if curriculum != "hepsi" and m.mufredat != curriculum:
            continue
        anahtar = (m.sinif, m.ders)
        kayitlar = out.setdefault(anahtar, {})
        # aynı kod birden çok materyalde geçebilir; ilk (en uzun metinli) tutulur
        mevcut = kayitlar.get(m.kazanim_kodu)
        metin = (m.kazanim or "").split("-", 1)[-1].strip() or (m.kazanim or "")
        if mevcut is None or len(metin) > len(mevcut["metin"]):
            kayitlar[m.kazanim_kodu] = {
                "kod": m.kazanim_kodu, "metin": metin,
                "unite": m.unite or "", "mufredat": m.mufredat}
    return {k: sorted(v.values(), key=lambda r: r["kod"]) for k, v in out.items()}
