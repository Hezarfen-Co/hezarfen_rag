"""Faz 1.8 — kiracılık (tenancy): OKUL İSTEKLE gelir, hiçbir env onu seçmez.

Backend'in hab/2 sözleşmesi her istek çerçevesinde `school` alanını ZORUNLU
kılar (`hezarfen_backend/src/ai/protocol.rs` → "School scoping"): AI filosu
tüm okullara PAYLAŞILAN tek servistir, bu yüzden okul el sıkışmada
sabitlenemez — *"a service pinned to one school would have to be run once per
customer"*. Bu modül o kuralın bu depodaki TEK ifadesidir.

KURAL: **okulla kapsanmış ya da hiç.** İçerik sahipsiz olamaz, okula
atfedilmemiş bir satır HİÇBİR okura görünmez (varsayılan/fallback yok), ve bir
okulun satırı başka bir okura ASLA görünmez.

  * **Okurun okulu** (istek): `normalize_school`. Geçersiz/ayrılmış bir değer
    reddedilir; `None` bir okul DEĞİLDİR — okulsuz okur hiçbir satır görmez
    (fail-closed).
  * **İçeriğin sahibi** (yazma): `require_owner`. Yeni yazmalarda ZORUNLUDUR —
    sahipsiz yazma bir hata, "paylaşılan bir satır" değil.
  * **Damgasız (eski) satırlar**: erişilemez. Geriye dönük bir "public" sayımı
    YOKTUR: VPS verisi mock ve tek kullanımlık (kullanıcı kararı, 2026-09-17),
    bu yüzden eski satırlar taşınmaz — kaynaktan yeniden indekslenir.
"""
from __future__ import annotations

import re

# Okul belirteci (tireli uuid; demo fixture adları da sığar): küçük harf/rakam,
# tire, alt çizgi. 64 karakter üstü üretilmez (Postgres kimlik sınırı 63).
_SCHOOL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class TenantError(ValueError):
    """Geçersiz okul değeri. Sessizce düzeltilmez — çağıran reddeder."""


def normalize_school(value) -> str | None:
    """İsteğin okulunu doğrular. `None`/`""` → `None` (okulsuz okur).

    Okulsuz okur bir hata değildir ama bir okul da değildir: hiçbir okulun
    içeriğini göremez. Geçersiz bir değer `TenantError` atar; çağıran bunu
    tipli bir redde çevirir (`unknown_school`)."""
    if value is None:
        return None
    metin = str(value).strip()
    if not metin:
        return None
    if not _SCHOOL_RE.match(metin):
        raise TenantError(f"geçersiz okul kimliği: {metin!r}")
    return metin


def require_owner(value) -> str:
    """YAZMA/korpus damgası: zorunlu ve gerçek bir okul olmalı.

    `None`/boş → `TenantError`: damgasız yazma bir hata, bir "paylaşılan satır"
    değil."""
    if value is None:
        raise TenantError("okul zorunlu: okulsuz satır/korpus yazılamaz")
    metin = str(value).strip()
    okul = normalize_school(metin)
    if not okul:
        raise TenantError("okul zorunlu: okulsuz satır/korpus yazılamaz")
    return okul


def content_visible(owner, reader) -> bool:
    """`owner` sahipli bir içerik `reader` okuruna görünür mü.

    TAM EŞİTLİK: damgasız satır (`None`/`""`) ya da başka bir okulun satırı
    görünmez. Okulsuz okur (`reader=None`) hiçbir satır görmez — "okul yok"
    diye "her şey" görünmez."""
    try:
        okur = normalize_school(reader)
    except TenantError:
        return False
    if not okur:
        return False
    try:
        sahip = require_owner(owner)
    except TenantError:
        return False           # damgasız/eski satır: erişilemez (taşınmaz)
    return sahip == okur


def visible_owners(reader) -> frozenset:
    """Okura görünür içerik sahipleri — yalnız okurun kendi okulu.

    Okulsuz okur için BOŞ küme (hiçbir satır görünmez)."""
    try:
        okur = normalize_school(reader)
    except TenantError:
        return frozenset()
    return frozenset({okur} if okur else set())
