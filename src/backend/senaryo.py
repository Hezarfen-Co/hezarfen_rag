"""Öğrenci senaryosu üretici — "öğrenci varmış gibi", ama UYDURMA İÇERİKSİZ.

Ne yapar: backend'in gerçek kayıt biçiminde (`/users/me`, `/classes`,
`/courses`, `/notes`, `/course-notes`) bir öğrenci kurar ve bunu `SahteOkuyucu`
ile okunabilir bir JSON'a yazar. Böylece backend ayakta olmadan da tüm ürün
yolu (kasa izolasyonu → retrieval → atıf) uçtan uca koşturulabilir.

NE **DEĞİLDİR** (kritik): bu bir test verisi üreticisidir, ölçüm verisi değil.
Notların metni MEB kazanım dosyalarından (`kazanimlar.json`) AYNEN alınır —
LLM'e yazdırılmaz, elle uydurulmaz. Gerekçe: uydurulmuş bir not, üzerinde
ölçülen her şeyi (atıf isabeti, kasa izolasyonu) anlamsız kılar; kazanım metni
ise gerçek müfredattır ve korpusta karşılığı vardır.

Senaryodaki kimlikler (ULID benzeri) deterministiktir: aynı girdiden aynı
kayıtlar çıkar, yani senaryo yeniden üretilebilir (EXP protokolü).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field

from .ders_eslesme import kasa_for, katla, korpus_dersleri

# Korpus slug -> backend'de görünecek ders başlığı (ders_eslesme'nin tersi yönü)
_BASLIK = {
    "biyoloji": "Biyoloji", "fizik": "Fizik", "kimya": "Kimya",
    "matematik": "Matematik", "geometri": "Geometri", "cografya": "Coğrafya",
    "felsefe": "Felsefe", "tarih": "Tarih", "edebiyat": "Türk Dili ve Edebiyatı",
    "ingilizce": "İngilizce", "almanca": "Almanca", "fransizca": "Fransızca",
    "arapca": "Arapça", "din-kulturu": "Din Kültürü ve Ahlak Bilgisi",
    "beden": "Beden Eğitimi", "bilisim": "Bilişim Teknolojileri",
    "cevre": "Çevre Eğitimi", "gorsel-sanatlar": "Görsel Sanatlar",
    "muzik": "Müzik", "saglik": "Sağlık Bilgisi",
    "fl-biyoloji": "Fen Lisesi Biyoloji", "fl-fizik": "Fen Lisesi Fizik",
    "fl-kimya": "Fen Lisesi Kimya", "fl-matematik": "Fen Lisesi Matematik",
}


def _kimlik(onek: str, *parcalar: str) -> str:
    """Deterministik, ULID görünümlü kayıt anahtarı (26 karakter, Crockford)."""
    ham = hashlib.sha256("|".join((onek,) + parcalar).encode("utf-8")).hexdigest()
    abc = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    sayi = int(ham[:32], 16)
    out = []
    for _ in range(26):
        sayi, kalan = divmod(sayi, 32)
        out.append(abc[kalan])
    return "".join(reversed(out))


def kazanimlari_oku(kok: str, kasa: str, sinif: str, ders: str) -> list[dict]:
    yol = os.path.join(kok, kasa, str(sinif), ders, "kazanimlar.json")
    if not os.path.isfile(yol):
        return []
    with open(yol, encoding="utf-8") as fh:
        veri = json.load(fh)
    return veri if isinstance(veri, list) else []


# --- MÜFREDAT SÜRÜMÜ UYUŞMAZLIĞI (2026-09-11, koşularak bulundu) ------------
#
# `kitap.pdf` ile `kazanimlar.json` AYNI MÜFREDATTAN GELMİYOR:
#   * kitap   -> "1. Tema ENERJİ / 2. Tema EKOLOJİ"  (Türkiye Yüzyılı Maarif
#                Modeli, tema yapısı)
#   * kazanım -> "ünite: Hücre Bölünmeleri, kod 10.1.1.2 Mitozu açıklar"
#                (eski müfredatın ünite/kazanım kodlaması)
#
# Ölçüldü — kazanım metninin ayırt edici sözcükleri kitap metninde geçiyor mu:
#   biyoloji %71 (Hücre Bölünmeleri ünitesinin TAMAMI kitapta yok: "mitoz"
#   198 sayfada 0 kez geçiyor), fizik %92 (mercek/prizma yok), kimya %96,
#   din-kültürü %97, İngilizce %98, coğrafya %100, felsefe %100.
#
# Bu, senaryo üretimi için kritik: kapsanmayan bir kazanımdan not üretirsek
# öğrenci kitapta OLMAYAN bir şeyi sorar, ürün doğru davranıp çekimser kalır
# ama bu bir RAG başarısızlığı gibi OKUNUR. Ölçüm verisi böyle zehirlenir.
# Bu yüzden not seçimi kapsanan kazanımlarla sınırlanır.
_DUR = {"aciklar", "ornekle", "orneklerle", "analiz", "eder", "edilir", "yapar",
        "kavrar", "yorumlar", "degerlendirir", "iliskilendirir", "siniflandirir",
        "tartisir", "canlilarda", "genel", "esaslarini", "ozelliklerini",
        "onemini", "uzerinde", "arasindaki", "iliskiyi", "cikarimlarda",
        "bulunur", "olusturur", "kullanarak"}
_METIN_ONBELLEK: dict[str, str] = {}


def _kitap_metni(kok: str, kasa: str, sinif: str, ders: str) -> str:
    """Kitabın ham metni (katlanmış). Ders başına bir kez okunur."""
    yol = os.path.join(kok, kasa, str(sinif), ders, "kitap.pdf")
    if yol in _METIN_ONBELLEK:
        return _METIN_ONBELLEK[yol]
    if not os.path.isfile(yol):
        _METIN_ONBELLEK[yol] = ""
        return ""
    try:
        import pymupdf
        with pymupdf.open(yol) as d:
            ham = "\n".join(d[i].get_text() for i in range(d.page_count))
    except Exception:
        ham = ""
    _METIN_ONBELLEK[yol] = katla(ham)
    return _METIN_ONBELLEK[yol]


def kazanim_kapsandi(kazanim: dict, kitap_metni: str, *, esik: float = 0.5) -> bool:
    """Kazanımın ayırt edici sözcüklerinin en az `esik` kadarı kitapta geçiyor mu.

    Kaba bir vekil ama YÖNÜ doğru verir: 0'a yakın bir kazanım kitapta kesinlikle
    yoktur. Tam ölçüm için `outputs/korpus-butunluk/` raporuna bakılır.
    """
    if not kitap_metni:
        return True                     # kitap okunamadıysa eleme yapma
    kelimeler = [w for w in re.findall(r"[a-z]{5,}", katla(kazanim.get("metin", "")))
                 if w not in _DUR]
    if not kelimeler:
        return True
    return sum(1 for w in kelimeler if w in kitap_metni) / len(kelimeler) >= esik


def kapsanan_kazanimlar(kok: str, kasa: str, sinif: str, ders: str) -> list[dict]:
    """Kitabın GERÇEKTEN cevaplayabileceği kazanımlar."""
    kz = kazanimlari_oku(kok, kasa, sinif, ders)
    if not kz:
        return []
    metin = _kitap_metni(kok, kasa, sinif, ders)
    return [k for k in kz if kazanim_kapsandi(k, metin)]


@dataclass
class Senaryo:
    okul: str
    ogrenci: dict
    sube: dict
    dersler: list[dict] = field(default_factory=list)
    notlar: list[dict] = field(default_factory=list)
    ders_notlari: list[dict] = field(default_factory=list)
    ogretmen: dict | None = None

    def yanitlar(self) -> list[dict]:
        """Backend uçlarının döndüreceği yanıtlar (`SahteOkuyucu` tablosu)."""
        y = [
            {"path": "/users/me", "query": None, "status": 200, "body": self.ogrenci},
            {"path": "/classes", "query": None, "status": 200,
             "body": {"items": [self.sube], "total": 1, "limit": 50, "offset": 0}},
            {"path": "/courses", "query": None, "status": 200,
             "body": {"items": self.dersler, "total": len(self.dersler),
                      "limit": 50, "offset": 0}},
            {"path": "/notes", "query": None, "status": 200,
             "body": {"items": self.notlar, "total": len(self.notlar),
                      "limit": 50, "offset": 0}},
        ]
        for ders in self.dersler:
            ait = [n for n in self.ders_notlari if n["course"] == ders["id"]]
            y.append({"path": "/course-notes", "query": f"course={ders['id']}",
                      "status": 200,
                      "body": {"items": ait, "total": len(ait),
                               "limit": 50, "offset": 0}})
        return y

    def to_dict(self) -> dict:
        return {"okul": self.okul, "ogrenci": self.ogrenci, "sube": self.sube,
                "ogretmen": self.ogretmen, "dersler": self.dersler,
                "notlar": self.notlar, "ders_notlari": self.ders_notlari,
                "yanitlar": self.yanitlar()}


def senaryo_kur(*, kok: str = "data", sinif: str = "10", okul: str = "demo",
                username: str = "ogrenci1", ad: str = "Zeynep", soyad: str = "Kaya",
                sube_adi: str | None = None, dersler: list[str] | None = None,
                not_sayisi: int = 3) -> Senaryo:
    """Diskte GERÇEKTEN bulunan derslerden bir öğrenci senaryosu kurar.

    `dersler=None` ise korpusta o sınıf için var olan TÜM dersler kullanılır —
    yani senaryo, indekslenebilir olanla birebir örtüşür. Var olmayan bir derse
    kayıt üretmek, ölçümde "kaynak bulunamadı"yı ürün hatası gibi gösterirdi.
    """
    kasa = kasa_for(sinif)
    if kasa is None:
        raise ValueError(f"sinif {sinif!r} icin kasa yok (5-12 bekleniyor)")
    mevcut = korpus_dersleri(kok, kasa, sinif)
    if not mevcut:
        raise ValueError(f"korpusta veri yok: {os.path.join(kok, kasa, str(sinif))}")
    secilen = [d for d in (dersler or mevcut) if d in mevcut]
    if not secilen:
        raise ValueError("secilen derslerin hicbiri korpusta yok")

    ogrenci_id = _kimlik("user", okul, username)
    ogretmen_id = _kimlik("user", okul, "ogretmen1")
    sube_id = _kimlik("class", okul, sinif, sube_adi or f"{sinif}-A")

    ogrenci = {"id": ogrenci_id, "username": username, "name": ad, "surname": soyad,
               "role": "student"}
    ogretmen = {"id": ogretmen_id, "username": "ogretmen1", "name": "Ayşe",
                "surname": "Yılmaz", "role": "teacher"}
    sube = {"id": sube_id, "name": sube_adi or f"{sinif}-A", "grade": str(sinif),
            "teacher": ogretmen_id}

    kurslar, notlar, ders_notlari = [], [], []
    for slug in secilen:
        kurs_id = _kimlik("course", okul, sinif, slug)
        kurslar.append({"id": kurs_id, "title": _BASLIK.get(slug, slug),
                        "description": f"{sinif}. sınıf {_BASLIK.get(slug, slug)}",
                        "kind": "course", "creator": ogretmen_id,
                        "teachers": [ogretmen_id]})
        kz = kapsanan_kazanimlar(kok, kasa, sinif, slug)
        if not kz:
            continue
        # ders notu: ilk ünitenin kazanımları (öğretmenin paylaştığı not).
        # KAPSANAN kazanımlardan seçilir — bkz. müfredat sürümü uyuşmazlığı notu.
        ilk_unite = kz[0].get("unite") or "Ünite 1"
        unite_kz = [k for k in kz if k.get("unite") == ilk_unite]
        ders_notlari.append({
            "id": _kimlik("cnote", okul, sinif, slug, ilk_unite),
            "course": kurs_id, "author": ogretmen_id,
            "title": f"{ilk_unite} — kazanımlar",
            "content": "\n".join(f"{k['kod']} {k['metin']}" for k in unite_kz)})
    # Öğrencinin KENDİ notları. DİKKAT: `secilen[:not_sayisi]` DEĞİL —
    # korpusta her dersin `kazanimlar.json`'u yok (ölçüldü: 10. sınıfta 19
    # dersin 11'inde var). İlk N dersi almak, alfabetik olarak başta duran
    # kazanımsız derslere denk gelip SIFIR not üretiyordu (koşunca görüldü).
    kazanimli = [d for d in secilen if kapsanan_kazanimlar(kok, kasa, sinif, d)]
    for i, slug in enumerate(kazanimli[:not_sayisi]):
        kz = kapsanan_kazanimlar(kok, kasa, sinif, slug)
        k = kz[min(i, len(kz) - 1)]
        notlar.append({
            "id": _kimlik("note", okul, username, slug, str(k.get("kazanim_id"))),
            "title": f"{_BASLIK.get(slug, slug)} — {k.get('unite', '')}".strip(" —"),
            "content": f"{k['kod']} {k['metin']}\n\n(Tekrar et: bu kazanımı "
                       f"anlamadım, örnek soru çözmeliyim.)"})

    return Senaryo(okul=okul, ogrenci=ogrenci, sube=sube, ogretmen=ogretmen,
                   dersler=kurslar, notlar=notlar, ders_notlari=ders_notlari)


def yaz(senaryo: Senaryo, yol: str) -> str:
    os.makedirs(os.path.dirname(yol) or ".", exist_ok=True)
    with open(yol, "w", encoding="utf-8") as fh:
        json.dump(senaryo.to_dict(), fh, ensure_ascii=False, indent=2)
    return yol
