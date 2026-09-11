"""Atıf işaretçisi (`[N]`) ayrıştırma — **TEK KAYNAK**.

M2-5 (#57, EXP-010/ACC-04 + ACC-14). Bu mantık eskiden iki yerde ayrı ayrı
duruyordu (`generate/generator.py` ve `summarize/summarizer.py`); ikincisinin
yorumu "KASITLI kod tekrarı ... regex davranışı değişirse HER İKİ modülde de
senkron güncellenmeli" diyordu. Böyle bir senkron sözü kodda tutulmaz — ACC-10'da
(parent genişletme) eval ile üretim tam bu şekilde ayrışmıştı ve yayınlanmış
sayılar üretimi temsil etmemişti. Bu yüzden ortak modüle alındı.
"""
from __future__ import annotations

import re

# ASCII rakam ZORUNLU: `\d` + `str.isdigit()` Unicode'dur, `[١]` (Arapça-Hint)
# `1` olarak kabul ediliyordu (koşularak kanıtlandı).
CITATION_RE = re.compile(r"\[([0-9,\s]+)\]", re.ASCII)


def parse_citations(text: str, n_sources: int | None = None):
    """`[N]` işaretlerini üç kovaya ayırır.

    Döner: `(atıflanan, hayalet, belirsiz_gruplar)`
      - **atıflanan**: bütün parçaları `1..n_sources` aralığında olan gruplar.
      - **hayalet**: TEK parçalı ve aralık dışı grup (`[9]`, `[1000000]`).
        Model gerçekten atıf yapmaya çalışmış ama çözülemiyor → `invalid_citations`
        olarak raporlanır ve kullanıcıya gösterilen metinden **kırpılır** (#62).
      - **belirsiz_gruplar**: ÇOK parçalı ve içinde aralık dışı parça olan grup
        (`[0,1]`, `[1, 9]`). Atıf sayılmaz, metinden **kırpılmaz**, hayalet de
        sayılmaz — yalnız telemetriye yazılır.

    Neden bu üçlü ayrım (#57/ACC-04) — koşulan kanıt:
    `"Olasılık değeri [0,1] aralığında yer alır [2]."` eski ayrıştırıcıda
    `[0,1,2]` üretiyordu; `0` hayalet sayılıyor ama **`1` geçerli bir kaynağa
    eşlenip s.5 UYDURMA atıf olarak cevaba ekleniyordu**. Model yalnız `[2]`'yi
    atıflamıştı. Golden set'te kimya ve fizik var; aralık gösterimi olağan.

    İki tasarım kararı ve gerekçeleri:

    1. *Çok parçalı grupta bir parça bile dışarıdaysa grubun TAMAMI atıl sayılır.*
       Zarar asimetriktir: veriyi atıf sanmak öğrenciye **gerçek sayfa numarasıyla
       uydurma bir atıf** gösterir (ürünün temel sözünün ihlali); atıfı veri sanmak
       yalnız bir atıf kaybettirir ve atıfsız kalan cevap zaten `ungrounded`
       kapısından çekimser olur. Bu yüzden `[1, 9]` artık `1`'i de atıflamaz.
    2. *Belirsiz grup metinden KIRPILMAZ.* `[0,1]` cümlenin içeriğidir; kırpmak
       "Olasılık değeri aralığında yer alır" gibi **bozuk bir cevap** üretir.
       Kırpma yalnız tek parçalı hayalet işaretler için güvenlidir.

    `n_sources` verilmezse aralık denetimi yapılmaz (ham ayrıştırma).
    """
    atiflanan: list[int] = []
    hayalet: list[int] = []
    belirsiz: list[str] = []
    for m in CITATION_RE.finditer(text):
        parts = [p.strip() for p in m.group(1).split(",")]
        if any(not p or not p.isascii() or not p.isdigit() for p in parts):
            continue                       # `[1.2]`, `[١]`, `[ ]` -> atıf değil
        sayilar = [int(p) for p in parts]
        if n_sources is None:
            atiflanan.extend(sayilar)
            continue
        disarida = [n for n in sayilar if n < 1 or n > n_sources]
        if not disarida:
            atiflanan.extend(sayilar)
        elif len(sayilar) == 1:
            hayalet.append(sayilar[0])
        else:
            belirsiz.append(m.group(0))
    return atiflanan, hayalet, belirsiz


def parse_citation_ns(text: str, n_sources: int | None = None) -> list[int]:
    """Yalnız atıflanan numaralar (bkz. `parse_citations`)."""
    return parse_citations(text, n_sources)[0]


def strip_phantom(text: str, hayalet: list[int]) -> str:
    """Kullanıcıya gösterilen metinden **çözülemeyen tek parçalı** `[N]`
    işaretlerini kırpar (#62/ACC-12: geçersiz işaret metinde duruyor ama
    karşılığında tıklanabilir atıf kaydı olmuyordu).

    Yalnız gösterim içindir; ölçümde ham metin kullanılır. Çok parçalı belirsiz
    gruplar KIRPILMAZ — onlar cümlenin içeriği olabilir (bkz. `parse_citations`).
    """
    if not hayalet:
        return text
    out = text
    for n in dict.fromkeys(hayalet):
        out = re.sub(r"\[\s*" + str(n) + r"\s*\]", "", out)
    out = re.sub(r"[ \t]+([.,;:!?])", r"\1", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def strip_citations(text: str) -> str:
    """Metinden atıf işaretlerini çıkarır (karşılaştırma/normalizasyon için)."""
    return CITATION_RE.sub("", text)
