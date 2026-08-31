"""Faz 0.6 — Türkçe metin normalizasyonu.

Gerçek ders-kitabı PDF metninde görülen sorunlar (data-driven):
- `\xad` (soft hyphen) ile satır-sonu hece bölünmesi: "mü\xadhendisliği" → "mühendisliği"
- `﻿`/zero-width görünmez karakterler: "﻿gen aktarımı"
- `-\n` ile kelime bölünmesi
- TR harf tuzağı: `"KİTAP".lower()` → combining-dot ("kitap" ile eşleşmez)

İlke ([[mimari]] §Türkçe): NFC; I/ı İ/i doğru; hece birleştir; bilimsel simge/
alt-indis KORUNUR; hem ham hem normalize alan tutulur. BM25 için en az bir alan
köklenmez → burada kök YOK, sadece normalize + eşleşme-katlama.
"""
from __future__ import annotations
import re
import unicodedata

_INVISIBLES = dict.fromkeys(map(ord, "﻿​‌‍⁠"), None)
_WS = re.compile(r"[ \t]+")
_MULTINL = re.compile(r"\n{3,}")


def nfc(s: str) -> str:
    """Unicode NFC (birleşik biçim) — combining dizileri tekilleştirir."""
    return unicodedata.normalize("NFC", s)


def tr_lower(s: str) -> str:
    """Türkçe-doğru küçültme: İ→i, I→ı (aksi halde combining-dot çıkar)."""
    return s.replace("İ", "i").replace("I", "ı").lower()


def tr_upper(s: str) -> str:
    """Türkçe-doğru büyütme: i→İ, ı→I."""
    return s.replace("i", "İ").replace("ı", "I").upper()


def strip_invisibles(s: str) -> str:
    """BOM / zero-width / word-joiner karakterlerini kaldır."""
    return s.translate(_INVISIBLES)


def join_hyphenation(s: str) -> str:
    """Satır-sonu hece bölünmesini birleştir:
    - `\xad` (soft hyphen) + opsiyonel boşluk/yeni-satır → kaldır (kelimeyi yapıştır)
    - `harf-\n harf` → yapıştır (PDF satır kırması)
    Not: normal tireli bileşikler (`neden-sonuç`) satır ORTASINDA korunur; yalnız
    satır-sonu birleşimi hedeflenir."""
    s = re.sub(r"\xad\s*", "", s)                       # soft hyphen (satır-içi/sonu)
    s = re.sub(r"(\w)-\n\s*(\w)", r"\1\2", s)           # kelime-\n devam → birleştir
    return s


def normalize(s: str) -> str:
    """Ham metin → temiz normalize metin (RAG'e beslenecek). Simgeler/alt-indis korunur."""
    if not s:
        return s
    s = strip_invisibles(s)
    s = join_hyphenation(s)
    s = nfc(s)
    s = _WS.sub(" ", s)                                 # yatay boşluk sıkıştır
    s = _MULTINL.sub("\n\n", s)                         # 3+ yeni-satır → 2
    # satır-başı/sonu boşlukları
    s = "\n".join(line.strip() for line in s.split("\n"))
    return s.strip()


def fold_for_match(s: str) -> str:
    """Eşleşme/anahtar-kelime için katlama: normalize + TR-küçült. Aksan KORUNUR
    (biyolojik terim bozulmasın); yalnız harf-durumu ve görünmezler eşitlenir."""
    return tr_lower(normalize(s))
