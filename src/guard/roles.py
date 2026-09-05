"""Faz 1.7b — sunucu-tarafı rol-türevli yetki (Çelebi rol-uzay modeli: ikili
ALLOW/DENY, sızıntısız-deny, backend-türevli matris).

Neden (RES-002 §2 — RagArt analizi): RagArt'ta kaynak seçimi + genel-bilgi
izni **client header**'ıyla belirleniyordu → herhangi bir istemci istediği
header'ı göndererek yetkisini yükseltebilirdi (authz tamamen dışarıda,
atlatılabilir). BİZİM İLKEMİZ: rol yetkisi İSTEMCİ HEADER'INDAN/GÖVDESİNDEN
ASLA türetilmez. `RoleContext`, kimlik-doğrulama katmanının (oturum/JWT/
sunucu-taraflı session) SUNUCU TARAFINDA ürettiği, istemcinin doğrudan
değiştiremeyeceği bir nesnedir — bu modül yalnız o nesneyi ALLOW/DENY'e
çevirir, nasıl üretildiğiyle ilgilenmez (o, auth katmanının işi).

Kapsam: `can_access` yalnız "bu rol bu sınıf+ders kapsamına erişebilir mi"
sorusuna İKİLİ (binary) cevap verir — belirsizlik/eksik veri DENY'e düşer
("no-leak deny": olası sızıntıdansa erişimi reddetmek tercih edilir).
Bu, YALNIZCA bir kapı/hook'tur; retrieval-SEVİYESİNDE filtreleme (yalnız
izinli chunk'ların getirilmesi) Faz 1.6 kapsamındadır — burada henüz
UYGULANMAZ (generator.py bu kapıyı ileride retrieval'e bağlayacak)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    PARENT = "parent"
    ADMIN = "admin"


@dataclass
class RoleContext:
    """Sunucu tarafında (auth katmanınca) türetilmiş rol + izinli kapsam.

    - `sinif`: rolün bağlı olduğu sınıf (öğrenci: kendi sınıfı; öğretmen/veli:
      sorumlu olduğu sınıf). ADMIN için anlamsız (her zaman ALLOW).
    - `ders_list`: rolün erişebileceği ders adları. BOŞ liste == henüz hiçbir
      derse atanmamış -> no-leak deny (aşağıda `can_access`).

    ASLA `request.headers`'tan doğrudan kurulmaz (bkz. dosya başı NOT)."""
    role: Role
    sinif: str | None = None
    ders_list: list[str] = field(default_factory=list)


def can_access(role_ctx: RoleContext | None, *, sinif: str, ders: str) -> bool:
    """İkili ALLOW/DENY. admin -> her zaman True (tam yetki). student/teacher/
    parent -> yalnız KENDİ `sinif`'i VE `ders_list`'i kapsıyorsa True; aksi
    halde (yanlış sınıf, ders_list dışı, ders_list boş, role_ctx eksik,
    tanınmayan rol) False — "no-leak deny": belirsizlikte erişim REDDEDİLİR,
    asla varsayılan olarak açılmaz."""
    if role_ctx is None:
        return False
    if role_ctx.role == Role.ADMIN:
        return True
    if role_ctx.role in (Role.STUDENT, Role.TEACHER, Role.PARENT):
        if not role_ctx.ders_list:          # derse hiç atanmamış -> no-leak deny
            return False
        if role_ctx.sinif != sinif:         # farklı sınıf -> kasa izolasyonu
            return False
        if ders not in role_ctx.ders_list:  # izinli olmayan ders -> deny
            return False
        return True
    return False   # tanınmayan/gelecekte eklenecek rol -> no-leak deny
