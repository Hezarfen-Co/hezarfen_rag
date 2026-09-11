"""Öğrenci bağlamı — backend'den okunan kimliği ürünün kasa izolasyonuna bağlar.

NEDEN BU KATMAN VAR
-------------------
Bizim erişim kararımız `guard/roles.can_access(role_ctx, sinif=, ders=)` ile
verilir ve `RoleContext(role, sinif, ders_list)` ister. Backend ise bu üçlüyü
**tek bir yerde tutmuyor**:

  * rol       -> `User.role`                       (`GET /users/me`)
  * sınıf     -> `ClassGroup.grade`                (`GET /classes` → üyesi olduğu şube)
  * ders_list -> `Enrollment` → `Course.title`     (`GET /courses`)

Yani öğrencinin "10. sınıf" olduğu bilgisi kullanıcı kaydında DEĞİL, üyesi
olduğu şubenin `grade` alanında duruyor (`domain/class_group.rs`). Üç okuma
birleştirilmeden kasa izolasyonu kurulamaz.

FAIL-CLOSED
-----------
Herhangi bir parça eksikse (şube yok, `grade` boş, hiçbir derse kayıtlı değil,
ders başlığı korpusta tanınmıyor) sonuç DAR olur, GENİŞ değil. `ders_list` boş
kalırsa `can_access` zaten her şeyi reddeder ("no-leak deny"). Burada uydurma
bir varsayılan (örn. "tüm dersler") ÜRETİLMEZ.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..guard.roles import Role, RoleContext
from .subject_map import subject_slug, vault_for


@dataclass
class PersonalNote:
    """Öğrencinin KENDİ notu (`Note` — `GET /notes`). Sahibi öğrencidir."""
    id: str
    title: str
    content: str


@dataclass
class CourseNote:
    """Öğretmenin ders notu (`CourseNote` — `GET /course-notes?course=`).
    RAG'e indekslenen budur (`rag.index`)."""
    id: str
    course: str
    title: str
    content: str


@dataclass
class StudentContext:
    """Bir öğrencinin ürün tarafındaki tam bağlamı."""
    user_id: str
    username: str
    ad: str
    rol: str
    sinif: str | None                    # ClassGroup.grade
    kasa: str | None                     # "ortaokul" | "lise"
    sube: str | None                     # ClassGroup.name
    dersler: list[str] = field(default_factory=list)       # korpus slug'ları
    unknown_subjects: list[str] = field(default_factory=list)
    notlar: list[PersonalNote] = field(default_factory=list)
    course_notes: list[CourseNote] = field(default_factory=list)

    def role_context(self) -> RoleContext | None:
        """Ürünün erişim kararında kullandığı bağlam. Rol tanınmazsa **None**
        (fail-closed; #43'te bu eksiklik erişim kontrolünü tümden atlatıyordu)."""
        try:
            r = Role(self.rol)
        except ValueError:
            return None
        return RoleContext(role=r, sinif=self.sinif, ders_list=list(self.dersler))


def _page_items(govde) -> list:
    """Backend sayfalı uçları `{items, total, limit, offset}` döndürür; bazı
    uçlar düz liste. İkisini de kabul et, başka bir şeyse boş liste."""
    if isinstance(govde, dict):
        return list(govde.get("items") or [])
    if isinstance(govde, list):
        return list(govde)
    return []


def build_context(okuyucu, user_id: str, *, with_course_notes: bool = True) -> StudentContext:
    """`user_id` için tam öğrenci bağlamını backend'den okuyup kurar.

    `okuyucu`: `.get(path, *, query=None, on_behalf_of=None) -> (status, body)`
    sunan herhangi bir nesne (köprü istemcisi ya da test sahtesi). Taşıma
    enjekte edilir — böylece bu mantık QUIC olmadan da test edilebilir.

    Okumalar öğrencinin KENDİ adına (`on_behalf_of`) yapılır: `ai` görevlisi
    okulun verisini göremez, öğrenci ise yalnız kendi görebildiğini görür.
    Yani yetki backend'de kalır, burada YENİDEN UYGULANMAZ.
    """
    durum, me = okuyucu.get("/users/me", on_behalf_of=user_id)
    if durum != 200 or not isinstance(me, dict):
        raise ValueError(f"/users/me okunamadi (status={durum})")

    sinif = sube = None
    durum, govde = okuyucu.get("/classes", on_behalf_of=user_id)
    if durum == 200:
        for sinif_kaydi in _page_items(govde):
            grade = (sinif_kaydi.get("grade") or "").strip()
            if grade:                      # grade'i OLAN ilk şube belirleyicidir
                sinif, sube = grade, sinif_kaydi.get("name")
                break

    dersler: list[str] = []
    taninmayan: list[str] = []
    ders_id_ad: dict[str, str] = {}
    durum, govde = okuyucu.get("/courses", on_behalf_of=user_id)
    if durum == 200:
        for kurs in _page_items(govde):
            baslik = kurs.get("title") or ""
            ders_id_ad[str(kurs.get("id"))] = baslik
            slug = subject_slug(baslik)
            if slug is None:
                taninmayan.append(baslik)   # sessizce eşleme UYDURMA
            elif slug not in dersler:
                dersler.append(slug)

    notlar: list[PersonalNote] = []
    durum, govde = okuyucu.get("/notes", on_behalf_of=user_id)
    if durum == 200:
        notlar = [PersonalNote(id=str(n.get("id")), title=n.get("title") or "",
                              content=n.get("content") or "")
                  for n in _page_items(govde)]

    course_notes: list[CourseNote] = []
    if with_course_notes:
        for kurs_id in ders_id_ad:
            durum, govde = okuyucu.get("/course-notes", query=f"course={kurs_id}",
                                       on_behalf_of=user_id)
            if durum != 200:
                continue                   # erişimi yoksa backend zaten reddeder
            course_notes.extend(
                CourseNote(id=str(n.get("id")), course=str(n.get("course")),
                         title=n.get("title") or "", content=n.get("content") or "")
                for n in _page_items(govde))

    return StudentContext(
        user_id=str(me.get("id") or user_id), username=me.get("username") or "",
        ad=" ".join(x for x in (me.get("name"), me.get("surname")) if x).strip(),
        rol=me.get("role") or "", sinif=sinif, kasa=vault_for(sinif) if sinif else None,
        sube=sube, dersler=dersler, unknown_subjects=taninmayan,
        notlar=notlar, course_notes=course_notes)
