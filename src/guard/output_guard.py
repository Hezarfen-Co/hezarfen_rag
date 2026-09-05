"""Faz 1.7b — çıktı guardrail: üretilen METİNDE ince kontrol (girdi geçse bile).

Neden: input_guard girdiyi geçirse bile (kalıp listesi kaçırdığında, ya da
retrieval'in getirdiği kaynak metninin kendisi sorunlu bir alıntı içerdiğinde)
LLM'in ÜRETTİĞİ cevap zararlı olabilir. Bu modül, generator.py'da LLM
çağrısından SONRA, aynı kalıp-listesini (input_guard._scan_harm_categories)
üretilen metne karşı çalıştırır — kaynak-sınırlı üretim (Faz 1.7a) zaten
fail-closed olduğundan bu İNCE bir ikinci savunma katmanıdır (defense-in-
depth). input_guard.py'daki NOT burada da geçerlidir: regex/kalıp tabanlıdır,
TEK savunma DEĞİLDİR."""
from __future__ import annotations

from .input_guard import GuardVerdict, _scan_harm_categories

_OUTPUT_REFUSE_MESSAGE = (
    "Üretilen cevap güvenlik kontrolünden geçemedi; bu soruyu şu an "
    "cevaplayamıyorum. Lütfen farklı bir şekilde sor."
)


def check_output(text: str | None) -> GuardVerdict:
    """Üretilen cevap metnini zararlı-içerik kalıplarına karşı kontrol eder.
    Boş/None metin -> allow. Not: injection kalıpları BURADA taranmaz (model
    çıktısı kullanıcıya yönelik bir istek değildir, injection girdi-tarafı bir
    tehdittir) — yalnız zararlı-İÇERİK kontrol edilir."""
    if not text or not text.strip():
        return GuardVerdict(action="allow", category="", message="", score=0.0)

    category = _scan_harm_categories(text)
    if category is not None:
        return GuardVerdict(action="refuse", category=category,
                            message=_OUTPUT_REFUSE_MESSAGE, score=1.0)

    return GuardVerdict(action="allow", category="", message="", score=0.0)
