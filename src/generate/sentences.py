"""Türkçe-duyarlı cümle bölme — atıf bütünlüğü ölçümü için (#56).

NEDEN AYRI BİR MODÜL: ürün sözü "cevabın HER cümlesi bir span'a bağlı". Kod
yalnız `if not citations` kontrolü yapıyordu, yani **bir tek atıf varsa geri
kalan tüm cümleler denetimsiz geçiyordu**. Koşulan kanıt (EXP-010/ACC-07):
5 cümleli bir cevabın 4'ü atıfsızdı ve 3'ü olgusal olarak yanlıştı
(47 ATP, ribozom nükleusta, 48 kromozom); sistem bunu `abstained=False,
reason=''` ile **temiz cevap** olarak döndürdü.

Bölme neden zor — naif `split(".")` bu metinlerde çalışmaz:
  * kısaltmalar: "vb.", "örn.", "bkz.", "M.Ö.", "Dr.", "s. 12"
  * ondalık ve sıra sayıları: "3.14", "10.1.1.2", "1. Tema", "2)"
  * madde imleri ve satır sonları cümle sınırıdır ama nokta taşımaz
  * atıf işaretleri noktadan SONRA gelebilir: "... olur [1]."
Yanlış bölme ölçümü iki yönde de bozar: fazla bölme atıfsız cümle oranını
şişirir, az bölme gizler. Bu yüzden bölücü ayrı ayrı test edilir.
"""
from __future__ import annotations

import re

# Sonunda nokta olan ama cümle BİTİRMEYEN kısaltmalar (küçük harfe indirilmiş).
_KISALTMA = {
    "vb", "vs", "örn", "bkz", "yy", "sy", "s", "bkz", "no", "nr", "dr", "doç",
    "prof", "av", "müh", "yrd", "bl", "böl", "şek", "tab", "res", "str", "ör",
    "mö", "ms", "tbmm", "abd", "vd", "age", "agm", "bknz", "hz", "alb", "gen",
    "min", "max", "ort", "yak", "ykl", "gr", "kg", "cm", "mm", "km", "ml", "lt",
}
# Cümle sonu adayı: . ! ? … ve ardından boşluk/satır sonu
_ADAY = re.compile(r"([.!?…]+)(\s+|$)")
# Atıf işareti (bölmeden ÖNCE korunur; cümleye ait sayılır)
_ATIF = re.compile(r"\[[0-9,\s]+\]", re.ASCII)
# Madde imi başlangıcı: "- ", "• ", "1. ", "2) ", "a) "
_MADDE = re.compile(r"^\s*(?:[-•*·–—]|\(?\d{1,2}[.)]|[a-zçğıöşü]\))\s+")


def _kisaltma_mi(metin: str, nokta_konumu: int) -> bool:
    """Noktadan önceki sözcük bir kısaltma mı (yani cümle bitmiyor mu)."""
    bas = nokta_konumu
    while bas > 0 and (metin[bas - 1].isalnum() or metin[bas - 1] in ".'’"):
        bas -= 1
    kelime = metin[bas:nokta_konumu].strip(".'’").lower()
    if not kelime:
        return False
    if kelime in _KISALTMA:
        return True
    # tek harf + nokta ("A.") -> kısaltma
    if len(kelime) == 1 and kelime.isalpha():
        return True
    # BAŞ HARF KISALTMASI: "M.Ö.", "T.C.", "A.B.D." — içinde nokta olan ve her
    # parçası 1-2 harflik bir belirteç. (İlk sürümde yoktu; "M.Ö. 300 yılında
    # yaşadı" cümlesi "M.Ö." ve "300 yılında..." diye İKİYE bölünüyordu ve
    # atıfsız cümle oranını yapay olarak şişiriyordu.)
    if "." in kelime:
        parcalar = [p for p in kelime.split(".") if p]
        if parcalar and all(len(p) <= 2 and p.isalpha() for p in parcalar):
            return True
    # sayı + nokta: "10.1.1.2", "3.14", "1. Tema" -> cümle sonu DEĞİL
    if kelime.isdigit():
        return True
    return False


def split_sentences(text: str) -> list[str]:
    """Metni cümlelere böler. Boş parçalar atılır, atıf işaretleri korunur.

    Satır sonları ve madde imleri de sınır sayılır: madde listesindeki her
    kalem bağımsız bir iddiadır ve ayrı ayrı dayanak ister.
    """
    if not text or not text.strip():
        return []
    out: list[str] = []
    for satir in text.splitlines():
        if not satir.strip():
            continue
        # madde imi varsa kendi başına bir parça olarak başlar
        parcalar = [satir]
        cumleler: list[str] = []
        for parca in parcalar:
            son = 0
            for m in _ADAY.finditer(parca):
                nokta = m.start()
                if _kisaltma_mi(parca, nokta):
                    continue
                cumle = parca[son:m.end(1)].strip()
                if cumle:
                    cumleler.append(cumle)
                son = m.end()
            kalan = parca[son:].strip()
            if kalan:
                cumleler.append(kalan)
        out.extend(c for c in cumleler if c.strip())
    return out


def is_cited(sentence: str) -> bool:
    """Cümle en az bir `[N]` atıf işareti taşıyor mu."""
    return bool(_ATIF.search(sentence or ""))


def is_bullet(sentence: str) -> bool:
    return bool(_MADDE.match(sentence or ""))


def citation_coverage(text: str) -> dict:
    """Atıf bütünlüğü ölçümü — kapı **A-03** bunun üzerinden hesaplanır.

    Döner: `n_sentences`, `n_cited_sentences`, `uncited_ratio`,
    `uncited_sentences` (metinleri).

    DÜRÜST SINIR: "atıf işareti yok" ile "dayanaksız" AYNI ŞEY DEĞİL. Model
    atıfı paragraf sonuna koyup önceki cümleleri kapsıyor olabilir. Bu yüzden
    bu bir ÜST SINIR ölçütüdür (atıfsız cümle oranı, gerçek dayanaksızlıktan
    büyük olabilir) ve politika kararı ölçüme bağlanmıştır — bkz.
    `generator.SENTENCE_POLICY`.
    """
    cumleler = split_sentences(text)
    atifli = [c for c in cumleler if is_cited(c)]
    atifsiz = [c for c in cumleler if not is_cited(c)]
    n = len(cumleler)
    return {"n_sentences": n, "n_cited_sentences": len(atifli),
            "uncited_ratio": round(len(atifsiz) / n, 4) if n else 0.0,
            "uncited_sentences": atifsiz}


def drop_uncited(text: str) -> tuple[str, list[str]]:
    """Atıfsız cümleleri metinden çıkarır. Döner: (kalan metin, atılanlar).

    Satır yapısı korunur (madde listeleri okunabilir kalsın).
    """
    atilan: list[str] = []
    tutulan_satirlar: list[str] = []
    for satir in text.splitlines():
        if not satir.strip():
            tutulan_satirlar.append("")
            continue
        cumleler = split_sentences(satir)
        tut = [c for c in cumleler if is_cited(c)]
        atilan.extend(c for c in cumleler if not is_cited(c))
        if tut:
            tutulan_satirlar.append(" ".join(tut))
    metin = "\n".join(tutulan_satirlar)
    metin = re.sub(r"\n{3,}", "\n\n", metin).strip()
    return metin, atilan
