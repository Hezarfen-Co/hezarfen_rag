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
    """Urun rol hiyerarsisi: parent < student < teacher < manager < admin.

    #43 (EXP-010/SEC-02): `MANAGER` bu enum'da EKSIKTI. Backend mesru bir mudur
    icin {"role":"manager",...} urettiginde `Role("manager")` ValueError atiyor,
    `_role_ctx` None donuyor ve ozet/soru yollarindaki `if role_ctx is not None:`
    korumasi yuzunden erisim kontrolu TAMAMEN atlaniyordu (fail-OPEN). Yani
    hiyerarsinin en yetkili rollerinden biri, kodda "taninmayan rol" olarak
    sinirsiz yetkiye donusuyordu."""
    PARENT = "parent"
    STUDENT = "student"
    TEACHER = "teacher"
    MANAGER = "manager"
    ADMIN = "admin"


@dataclass
class RoleContext:
    """Sunucu tarafında (auth katmanınca) türetilmiş rol + izinli kapsam.

    - `sinif`: rolün bağlı olduğu sınıf (öğrenci: kendi sınıfı; öğretmen/veli:
      sorumlu olduğu sınıf). ADMIN için anlamsız (her zaman ALLOW).
    - `ders_list`: rolün erişebileceği ders adları. BOŞ liste == henüz hiçbir
      derse atanmamış -> no-leak deny (aşağıda `can_access`).

    ASLA `request.headers`'tan doğrudan kurulmaz (bkz. dosya başı NOT).

    `scope_pairs`: rag.chat'in YENİ biçimi — (sınıf, ders) ÇİFTLERİ. Doluysa
    `can_access` KARARI bunlardan verilir (aşağıda); `sinif`/`ders_list` alanları
    yalnız eski okuyucular (iz, yönlendirme) için türetilmiş ÖZET'tir. Çift
    biçimi kullanılırken `sinif`+`ders_list`'in KARTEZYEN çarpımına düşülmez —
    bkz. `bridge/contract.RagScopePair` (çapraz-çarpım güvenliği)."""
    role: Role
    sinif: str | None = None
    ders_list: list[str] = field(default_factory=list)
    scope_pairs: list | None = None


def _same_grade(a, b) -> bool:
    """Sınıf eşitliği — `None` ve `""` ikisi de "sınıfsız" demektir (okul
    kulübü/etüt korpusu). ÇİFT eşleşmesi TAM olmalıdır: sınıfsız bir çift,
    sınıflı bir korpusu AÇMAZ (çapraz-çarpım güvenliği)."""
    na = None if a in (None, "") else str(a)
    nb = None if b in (None, "") else str(b)
    return na == nb


def can_access(role_ctx: RoleContext | None, *, sinif: str, ders: str) -> bool:
    """İkili ALLOW/DENY. admin -> her zaman True (tam yetki). student/teacher/
    parent -> yalnız KENDİ `sinif`'i VE `ders_list`'i kapsıyorsa True; aksi
    halde (yanlış sınıf, ders_list dışı, ders_list boş, role_ctx eksik,
    tanınmayan rol) False — "no-leak deny": belirsizlikte erişim REDDEDİLİR,
    asla varsayılan olarak açılmaz.

    `scope_pairs` doluysa (rag.chat çift biçimi): erişim ancak (sinif, ders)
    ÇİFTLERDEN birine TAM uyarsa açılır. `sinif=None`/`""` çifti SADECE
    sınıfsız (okul kulübü/etüt) korpusla eşleşir; sınıflı bir korpusu AÇMAZ.
    Kartezyen BİRLEŞİM yoktur."""
    if role_ctx is None:
        return False
    if role_ctx.role == Role.ADMIN:
        return True
    if role_ctx.role == Role.MANAGER:
        # Mudur: kurum genelinde yetkili (backend'in urettigi rol zaten kurum
        # kapsamli). ADMIN gibi kapsam-bagimsiz ALLOW; #43 ile eklendi.
        return True
    if role_ctx.scope_pairs is not None:
        return any(_same_grade(p[0], sinif) and str(p[1]) == str(ders)
                   for p in role_ctx.scope_pairs)
    if role_ctx.role in (Role.STUDENT, Role.TEACHER, Role.PARENT):
        if not role_ctx.ders_list:          # derse hiç atanmamış -> no-leak deny
            return False
        if role_ctx.sinif != sinif:         # farklı sınıf -> kasa izolasyonu
            return False
        if ders not in role_ctx.ders_list:  # izinli olmayan ders -> deny
            return False
        return True
    return False   # tanınmayan/gelecekte eklenecek rol -> no-leak deny
