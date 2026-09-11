"""Sahte okul — backend kayıt biçiminde tam bir veri kümesi.

`senaryo.py` TEK öğrenci kurar; bu modül bir OKUL kurar: birden çok şube,
öğretmen, veli, farklı ders kayıtları. İki iş için:

1. **Tohumlama.** Kayıtlar backend'in gerçek biçimindedir (`User`, `ClassGroup`,
   `ClassMember`, `Course`, `Enrollment`, `Note`, `CourseNote`), yani ayakta bir
   backend'e olduğu gibi POST edilebilir.
2. **Çevrimdışı koşum.** `OkulSahtesi` bir kullanıcı adına okuma yapar ve
   **backend'in yetki davranışını taklit eder**: öğrenci yalnız kendi şubesini,
   kendi kayıtlı derslerini ve KENDİ notlarını görür.

İkincisi kritik: sahte okuyucu her kullanıcıya her şeyi döndürseydi kasa
izolasyonu testlerimiz **hiçbir şey ölçmezdi** — sızıntı olsa da geçerlerdi.

UYDURMA İÇERİK YOK: not metinleri MEB kazanımlarından aynen alınır ve yalnız
kitabın gerçekten kapsadığı kazanımlar kullanılır (bkz. `senaryo.py`'deki
müfredat sürümü uyuşmazlığı notu · #94).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .ders_eslesme import kasa_for, korpus_dersleri
from .senaryo import _BASLIK, _kimlik, kapsanan_kazanimlar

# Öğrenci adları — senaryo sabiti; backend'deki `mockdata/people.json` ile
# tutarlı tutuldu ki iki taraf aynı kişilerden söz etsin.
_OGRENCILER = [("ogrenci1", "Zeynep", "Kaya"), ("ogrenci2", "Emre", "Şahin"),
               ("ogrenci3", "Elif", "Aydın"), ("ogrenci4", "Burak", "Çelik"),
               ("ogrenci5", "Deniz", "Arslan")]
_OGRETMENLER = [("ogretmen1", "Ayşe", "Yılmaz"), ("ogretmen2", "Mehmet", "Demir")]
_VELILER = [("veli1", "Hasan", "Kaya", "ogrenci1")]


@dataclass
class Okul:
    slug: str
    users: list[dict] = field(default_factory=list)
    classes: list[dict] = field(default_factory=list)
    class_members: list[dict] = field(default_factory=list)
    courses: list[dict] = field(default_factory=list)
    enrollments: list[dict] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)
    course_notes: list[dict] = field(default_factory=list)
    parent_links: list[dict] = field(default_factory=list)

    def kullanici(self, username: str) -> dict | None:
        return next((u for u in self.users if u["username"] == username), None)

    def ozet(self) -> dict:
        return {"okul": self.slug, "kullanici": len(self.users),
                "sube": len(self.classes), "uyelik": len(self.class_members),
                "ders": len(self.courses), "kayit": len(self.enrollments),
                "kisisel_not": len(self.notes), "ders_notu": len(self.course_notes),
                "veli_bagi": len(self.parent_links)}

    def to_dict(self) -> dict:
        return {"okul": self.slug, "ozet": self.ozet(), "users": self.users,
                "classes": self.classes, "class_members": self.class_members,
                "courses": self.courses, "enrollments": self.enrollments,
                "notes": self.notes, "course_notes": self.course_notes,
                "parent_links": self.parent_links}


def okul_kur(*, kok: str = "data", okul: str = "demo", sinif: str = "10",
             subeler: tuple[str, ...] = ("A", "B"),
             sube_basina_ders: int = 6, ogrenci_basina_not: int = 3) -> Okul:
    """Diskte GERÇEKTEN bulunan derslerden bir okul kurar.

    `sube_basina_ders`: her şube farklı bir ders kümesi alır (kaydırmalı), böylece
    "aynı sınıfta ama farklı derste" durumu da kurulur — izolasyon yalnız sınıfa
    değil derse de bakıyor, tek ders kümesiyle bu ölçülemezdi.
    """
    kasa = kasa_for(sinif)
    if kasa is None:
        raise ValueError(f"sinif {sinif!r} icin kasa yok (5-12 bekleniyor)")
    mevcut = korpus_dersleri(kok, kasa, sinif)
    if not mevcut:
        raise ValueError(f"korpusta veri yok: {os.path.join(kok, kasa, str(sinif))}")
    # kazanımı OLAN dersler öne alınır: notu olmayan bir ders senaryoyu boşaltır
    kazanimli = [d for d in mevcut if kapsanan_kazanimlar(kok, kasa, sinif, d)]
    sirali = kazanimli + [d for d in mevcut if d not in kazanimli]

    o = Okul(slug=okul)
    for kul, ad, soyad in _OGRETMENLER:
        o.users.append({"id": _kimlik("user", okul, kul), "username": kul,
                        "name": ad, "surname": soyad, "role": "teacher"})
    for kul, ad, soyad, _ in _VELILER:
        o.users.append({"id": _kimlik("user", okul, kul), "username": kul,
                        "name": ad, "surname": soyad, "role": "parent"})

    ogretmen_id = o.kullanici("ogretmen1")["id"]
    ders_kayit: dict[str, str] = {}          # slug -> course id (okul genelinde tek)

    for i, sube_harfi in enumerate(subeler):
        sube_adi = f"{sinif}-{sube_harfi}"
        sube_id = _kimlik("class", okul, sinif, sube_adi)
        sube_ogretmeni = o.users[i % len(_OGRETMENLER)]["id"]
        o.classes.append({"id": sube_id, "name": sube_adi, "grade": str(sinif),
                          "creator": ogretmen_id, "teacher": sube_ogretmeni})

        # kaydırmalı ders kümesi: şubeler kısmen örtüşür, kısmen ayrışır
        basla = (i * 2) % max(1, len(sirali))
        sube_dersleri = [sirali[(basla + j) % len(sirali)]
                         for j in range(min(sube_basina_ders, len(sirali)))]

        for slug in sube_dersleri:
            if slug not in ders_kayit:
                kurs_id = _kimlik("course", okul, sinif, slug)
                ders_kayit[slug] = kurs_id
                o.courses.append({"id": kurs_id, "title": _BASLIK.get(slug, slug),
                                  "description": f"{sinif}. sınıf {_BASLIK.get(slug, slug)}",
                                  "kind": "course", "creator": ogretmen_id,
                                  "teachers": [sube_ogretmeni]})
                kz = kapsanan_kazanimlar(kok, kasa, sinif, slug)
                if kz:
                    ilk = kz[0].get("unite") or "Ünite 1"
                    grup = [k for k in kz if k.get("unite") == ilk]
                    o.course_notes.append({
                        "id": _kimlik("cnote", okul, sinif, slug, ilk),
                        "course": kurs_id, "author": sube_ogretmeni,
                        "title": f"{ilk} — kazanımlar",
                        "content": "\n".join(f"{k['kod']} {k['metin']}" for k in grup)})

        # şubenin öğrencileri (dönüşümlü dağıtılır)
        for j, (kul, ad, soyad) in enumerate(_OGRENCILER):
            if j % len(subeler) != i:
                continue
            uid = _kimlik("user", okul, kul)
            o.users.append({"id": uid, "username": kul, "name": ad,
                            "surname": soyad, "role": "student"})
            o.class_members.append({"id": _kimlik("member", okul, sube_adi, kul),
                                    "class": sube_id, "user": uid,
                                    "added_by": ogretmen_id})
            for slug in sube_dersleri:
                o.enrollments.append({
                    "id": _kimlik("enroll", okul, kul, slug),
                    "course": ders_kayit[slug], "user": uid,
                    "enrolled_by": ogretmen_id, "source": sube_id})
            # öğrencinin KENDİ notları — her öğrenci FARKLI kazanımlardan
            kazanimli_dersler = [s for s in sube_dersleri
                                 if kapsanan_kazanimlar(kok, kasa, sinif, s)]
            for n, slug in enumerate(kazanimli_dersler[:ogrenci_basina_not]):
                kz = kapsanan_kazanimlar(kok, kasa, sinif, slug)
                k = kz[(j + n) % len(kz)]          # öğrenciye göre kaydır
                o.notes.append({
                    "id": _kimlik("note", okul, kul, slug, str(k.get("kazanim_id"))),
                    "user": uid,
                    "title": f"{_BASLIK.get(slug, slug)} — {k.get('unite', '')}".strip(" —"),
                    "content": f"{k['kod']} {k['metin']}\n\n"
                               f"(Kendi notum: bunu tekrar etmeliyim.)"})

    for kul, _ad, _soyad, cocuk in _VELILER:
        o.parent_links.append({"id": _kimlik("plink", okul, kul, cocuk),
                               "parent": _kimlik("user", okul, kul),
                               "student": _kimlik("user", okul, cocuk)})
    return o


class OkulSahtesi:
    """Bir kullanıcı adına okuyan sahte backend.

    Backend'in YETKİ davranışını taklit eder — her kullanıcıya her şeyi
    döndürseydi izolasyon testlerimiz hiçbir şey ölçmezdi.

    Kural (backend'in gerçek davranışının sadeleştirilmiş hâli):
      * `/users/me`      -> `on_behalf_of` kullanıcısı
      * `/classes`       -> öğrenci: üyesi olduğu şubeler · öğretmen: öğretmeni
                            olduğu şubeler · yönetici/admin: hepsi
      * `/courses`       -> öğrenci: kayıtlı olduğu dersler · öğretmen: verdiği
      * `/notes`         -> YALNIZ kendi notları (`Note.user`)
      * `/course-notes`  -> yalnız erişebildiği dersin notları, aksi hâlde 403

    DÜRÜST SINIR 1: bu bir yetki MOTORU değil, davranış taklididir. Gerçek karar
    backend'dedir; burada amaç, çevrimdışı koşumun gerçeğe yakın davranması.

    DÜRÜST SINIR 2 — **VELİ YOLU KURULMADI.** `parent_links` üretiliyor ama
    veli hiçbir şey göremiyor: `/classes`, `/courses`, `/notes` üçü de boş
    döner (ölçüldü). Sebep, velinin çocuğunun verisine hangi uçtan eriştiğini
    backend'de henüz doğrulamamış olmam. Boş bırakmak, uydurulmuş bir veli
    görünürlüğü kurmaktan yeğdir: yanlış bir kural, üzerine kurulacak her
    izolasyon ölçümünü sessizce geçersiz kılardı. Bkz. `docs/Backlog.md` BL-011.
    """

    def __init__(self, okul: Okul):
        self.okul = okul
        self.cagrilar: list[tuple[str, str | None, str | None]] = []

    # -- yardımcılar ----------------------------------------------------
    def _user(self, uid):
        return next((u for u in self.okul.users if u["id"] == uid), None)

    def _subeleri(self, u):
        if u["role"] in ("manager", "admin"):
            return list(self.okul.classes)
        if u["role"] == "teacher":
            return [c for c in self.okul.classes if c.get("teacher") == u["id"]]
        uyelik = {m["class"] for m in self.okul.class_members if m["user"] == u["id"]}
        return [c for c in self.okul.classes if c["id"] in uyelik]

    def _dersleri(self, u):
        if u["role"] in ("manager", "admin"):
            return list(self.okul.courses)
        if u["role"] == "teacher":
            return [c for c in self.okul.courses if u["id"] in (c.get("teachers") or [])]
        kayitli = {e["course"] for e in self.okul.enrollments if e["user"] == u["id"]}
        return [c for c in self.okul.courses if c["id"] in kayitli]

    @staticmethod
    def _sayfa(items):
        return {"items": items, "total": len(items), "limit": 50, "offset": 0}

    # -- okuma ----------------------------------------------------------
    def get(self, path: str, *, query: str | None = None,
            on_behalf_of: str | None = None) -> tuple[int, object]:
        self.cagrilar.append((path, query, on_behalf_of))
        if on_behalf_of is None:
            return 403, None            # `ai` görevlisi okul verisini göremez
        u = self._user(on_behalf_of)
        if u is None:
            return 404, None
        if path == "/users/me":
            return 200, u
        if path == "/classes":
            return 200, self._sayfa(self._subeleri(u))
        if path == "/courses":
            return 200, self._sayfa(self._dersleri(u))
        if path == "/notes":
            return 200, self._sayfa([n for n in self.okul.notes
                                     if n["user"] == u["id"]])
        if path == "/course-notes":
            kurs = (query or "").split("course=", 1)[-1] if query else ""
            if not kurs:
                return 400, None
            if kurs not in {c["id"] for c in self._dersleri(u)}:
                return 403, None        # erişimi olmayan dersin notu
            return 200, self._sayfa([n for n in self.okul.course_notes
                                     if n["course"] == kurs])
        return 404, None


def yaz(okul: Okul, dizin: str) -> list[str]:
    """Okulu diske yazar: tam veri kümesi + kullanıcı başına okuma anlık görüntüsü."""
    os.makedirs(dizin, exist_ok=True)
    yazilan = []
    tam = os.path.join(dizin, "okul.json")
    with open(tam, "w", encoding="utf-8") as fh:
        json.dump(okul.to_dict(), fh, ensure_ascii=False, indent=2)
    yazilan.append(tam)

    sahte = OkulSahtesi(okul)
    for u in okul.users:
        yanitlar = []
        for path, query in [("/users/me", None), ("/classes", None),
                            ("/courses", None), ("/notes", None)]:
            st, body = sahte.get(path, query=query, on_behalf_of=u["id"])
            yanitlar.append({"path": path, "query": query, "status": st, "body": body})
        _, dersler = sahte.get("/courses", on_behalf_of=u["id"])
        for k in (dersler or {}).get("items", []):
            q = f"course={k['id']}"
            st, body = sahte.get("/course-notes", query=q, on_behalf_of=u["id"])
            yanitlar.append({"path": "/course-notes", "query": q,
                             "status": st, "body": body})
        yol = os.path.join(dizin, f"okuma-{u['username']}.json")
        with open(yol, "w", encoding="utf-8") as fh:
            json.dump({"okul": okul.slug, "user_id": u["id"], "rol": u["role"],
                       "yanitlar": yanitlar}, fh, ensure_ascii=False, indent=2)
        yazilan.append(yol)
    return yazilan
