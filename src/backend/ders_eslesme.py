"""Backend dersi ↔ korpus dersi eşlemesi.

Backend'de bir ders `Course{title, kind}`'dır; korpusta ise `data/<kasa>/<sınıf>/
<ders-slug>/` klasörüdür. İkisi AYNI ŞEY DEĞİL: backend'deki ders bir okulun
açtığı sınıf-dersi (şubeye bağlı, öğretmeni var), korpustaki ders MEB kitabının
konu alanı. Köprü kurulmazsa kasa izolasyonu (`can_access(sinif=, ders=)`)
backend'den gelen adla eşleşmez ve her şey sessizce DENY olur.

ÖLÇÜLEN GERÇEK (2026-09-11, `data/lise/10`): korpusta 19 ders slug'ı var.
Eşleme bu slug'lara yapılır; tanınmayan başlık `None` döner ve çağıran
FAIL-CLOSED davranır (uydurma eşleme YOK).
"""
from __future__ import annotations

import os
import re
import unicodedata

# Korpus slug -> backend'de görülebilecek başlık biçimleri (küçük harf, katlanmış)
_ESLESME: dict[str, tuple[str, ...]] = {
    "biyoloji":       ("biyoloji", "bio"),
    "fizik":          ("fizik",),
    "kimya":          ("kimya",),
    "matematik":      ("matematik", "mat", "temel matematik"),
    "geometri":       ("geometri",),
    "cografya":       ("cografya", "coğrafya"),
    "felsefe":        ("felsefe",),
    "tarih":          ("tarih",),
    "edebiyat":       ("edebiyat", "turk dili ve edebiyati", "türk dili ve edebiyatı"),
    "ingilizce":      ("ingilizce", "english"),
    "almanca":        ("almanca",),
    "fransizca":      ("fransizca", "fransızca"),
    "arapca":         ("arapca", "arapça"),
    "din-kulturu":    ("din kulturu", "din kültürü",
                   "din kulturu ve ahlak bilgisi",
                   "din kültürü ve ahlak bilgisi"),
    "beden":          ("beden", "beden egitimi", "beden eğitimi", "spor"),
    "bilisim":        ("bilisim", "bilişim", "bilgisayar", "informatik",
                   "bilisim teknolojileri", "bilişim teknolojileri"),
    "cevre":          ("cevre", "çevre", "cevre egitimi", "çevre eğitimi"),
    "gorsel-sanatlar": ("gorsel sanatlar", "görsel sanatlar", "resim"),
    "muzik":          ("muzik", "müzik"),
    "saglik":         ("saglik", "sağlık", "saglik bilgisi", "sağlık bilgisi"),
    # fen lisesi varyantlari korpusta ayri klasor
    "fl-biyoloji":    ("fen lisesi biyoloji", "fl biyoloji"),
    "fl-fizik":       ("fen lisesi fizik", "fl fizik"),
    "fl-kimya":       ("fen lisesi kimya", "fl kimya"),
    "fl-matematik":   ("fen lisesi matematik", "fl matematik"),
}


def katla(metin: str) -> str:
    """Türkçe-duyarlı karşılaştırma biçimi: İ/ı katlaması + aksan atma.

    `str.lower()` TEK BAŞINA YETMEZ: "İNGİLİZCE".lower() Türkçe olmayan
    yerelde "i̇ngilizce" (birleşen noktalı i) üretir ve eşleşme kaçar.
    """
    if not metin:
        return ""
    m = metin.replace("İ", "i").replace("I", "ı").replace("ı", "i")
    m = m.lower()
    m = unicodedata.normalize("NFKD", m)
    m = "".join(ch for ch in m if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", m).strip()


_TERS: dict[str, str] = {}
for _slug, _adlar in _ESLESME.items():
    _TERS[katla(_slug)] = _slug
    for _ad in _adlar:
        _TERS[katla(_ad)] = _slug


def ders_slug(backend_basligi: str | None) -> str | None:
    """Backend ders başlığı → korpus ders slug'ı. Tanınmazsa **None**.

    None dönmesi bir hata değil, bir KARARDIR: uydurma bir slug üretmek
    (örn. başlığı olduğu gibi slug'a çevirmek) var olmayan bir kasaya erişim
    izni gibi görünür. Çağıran fail-closed davranır.
    """
    if not backend_basligi:
        return None
    return _TERS.get(katla(backend_basligi))


def korpus_dersleri(kok: str, kasa: str, sinif: str) -> list[str]:
    """Diskte GERÇEKTEN bulunan ders slug'ları (`data/<kasa>/<sınıf>/*`).

    Eşleme tablosu değil, dosya sistemi gerçeği. İkisi ayrıştığında ölçüt
    budur — indekslenemeyen bir derse erişim izni vermek anlamsızdır.
    """
    yol = os.path.join(kok, kasa, str(sinif))
    if not os.path.isdir(yol):
        return []
    return sorted(a for a in os.listdir(yol) if os.path.isdir(os.path.join(yol, a)))


def kasa_for(sinif: str | int) -> str | None:
    """Sınıf → kasa ("ortaokul" 5-8, "lise" 9-12). Dışındaysa None."""
    try:
        n = int(str(sinif).strip())
    except (TypeError, ValueError):
        return None
    if 5 <= n <= 8:
        return "ortaokul"
    if 9 <= n <= 12:
        return "lise"
    return None
