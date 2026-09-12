"""Testler için korpus bulucu — TEK KAYNAK.

NEDEN VAR: her entegrasyon/e2e testi kitap yolunu kendi içinde sabitliyordu
(`data/lise/12/biyoloji/kitap.pdf`). O kitap bu depoda yok (#92) ve sonuç
şuydu: **47 atlanan testin 46'sı** bu yüzden atlanıyordu — yani entegrasyon
ve e2e süitinin TAMAMI ölüydü, hiç koşmuyordu. Birim testleri yeşil
görünürken gerçek boru hattı hiç sınanmıyordu.

Elimizde 10. sınıf korpusu var ve o da aynı boru hattını sınar. Bu modül
"hangi kitap varsa onu kullan" der; hiçbiri yoksa test atlanır.

`HEZARFEN_TEST_BOOK` ile açıkça bir kitap verilebilir (CI'da sabitlemek için).
"""
from __future__ import annotations

import functools
import os
import unittest

# Tercih sırası: açık env → 10 (tam korpus) → diğer sınıflar.
_ADAYLAR = [
    ("10", "biyoloji"), ("10", "fizik"), ("10", "kimya"), ("10", "cografya"),
    ("11", "biyoloji"), ("12", "biyoloji"), ("9", "biyoloji"),
]


@functools.lru_cache(maxsize=1)
def find_book() -> tuple[str, str, str] | None:
    """(yol, sinif, ders) ya da None."""
    acik = os.environ.get("HEZARFEN_TEST_BOOK")
    if acik and os.path.isfile(acik):
        parcalar = acik.replace("\\", "/").split("/")
        try:
            i = parcalar.index("lise")
            return acik, parcalar[i + 1], parcalar[i + 2]
        except (ValueError, IndexError):
            return acik, "10", "biyoloji"
    for sinif, ders in _ADAYLAR:
        yol = os.path.join("data", "lise", sinif, ders, "kitap.pdf")
        if os.path.isfile(yol):
            return yol, sinif, ders
    return None


def book_path() -> str | None:
    b = find_book()
    return b[0] if b else None


def requires_book(fn=None):
    """Sınıf/metot dekoratörü: korpus yoksa atla."""
    b = find_book()
    dec = unittest.skipUnless(b is not None,
                              "korpus yok: data/lise/<sınıf>/<ders>/kitap.pdf")
    return dec if fn is None else dec(fn)


def requires_objectives(fn=None):
    """Kazanım dosyası da gerekiyorsa."""
    b = find_book()
    var = False
    if b:
        d = os.path.dirname(b[0])
        var = (os.path.isfile(os.path.join(d, "kazanimlar.json"))
               or os.path.isfile(os.path.join(d, "objectives.json")))
    dec = unittest.skipUnless(var, "kazanım dosyası yok")
    return dec if fn is None else dec(fn)


def requires_llm(fn=None):
    """Gerçek LLM anahtarı gerekiyorsa."""
    var = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
               or os.environ.get("NVIDIA_API_KEY"))
    dec = unittest.skipUnless(var, "LLM anahtarı yok")
    return dec if fn is None else dec(fn)


def objectives_path() -> str | None:
    """Kazanım dosyası (`kazanimlar.json` ya da katalogdan `objectives.json`)."""
    b = find_book()
    if not b:
        return None
    d = os.path.dirname(b[0])
    for ad in ("kazanimlar.json", "objectives.json"):
        yol = os.path.join(d, ad)
        if os.path.isfile(yol):
            return yol
    return None


def needle_query(doc, *, min_words: int = 18, index: int = 0) -> str:
    """Kitabın KENDİ metninden türetilmiş, kesin bulunabilir bir sorgu.

    Testlerin sorguyu sabitlemesi korpusa bağımlılık yaratır: "DNA nedir?"
    12. sınıf kitabında çalışır, 10. sınıfta `insufficient_data` döner ve
    test kendi verisine çakılır. Sorguyu kitabın içinden almak her korpusta
    çalışır ve testin ölçtüğü şeyi (boru hattı sağlam mı) korur.
    """
    uygun = [u for u in doc.retrievable_units
             if len((u.text or "").split()) >= min_words]
    if not uygun:
        raise unittest.SkipTest("korpusta yeterince uzun birim yok")
    u = uygun[min(index, len(uygun) - 1) if index else len(uygun) // 2]
    return " ".join(u.text.split()[:24])


# --- PAYLAŞIMLI MODELLER ---------------------------------------------------
#
# NEDEN: entegrasyon testleri canlandırılınca (47 atlanan → 2) her test modülü
# kendi `BGEM3Embedder()` + `BGEReranker()` örneğini VRAM'e yüklemeye başladı
# ve süit **CUDA out of memory** ile düştü (7,57 GiB / 7,65 GiB). Modeller
# durumsuzdur; tek örnek yeterli. Yan fayda: süit belirgin biçimde hızlanır
# (her modül ~10 s model yükleme ödemiyor).

_EMBEDDER = None
_RERANKER = None


def shared_embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        from src.embed import BGEM3Embedder
        _EMBEDDER = BGEM3Embedder()
    return _EMBEDDER


def shared_reranker():
    global _RERANKER
    if _RERANKER is None:
        from src.rerank import BGEReranker
        _RERANKER = BGEReranker()
    return _RERANKER
