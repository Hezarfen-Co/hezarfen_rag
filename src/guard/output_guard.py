"""Faz 1.7b — çıktı guardrail: üretilen METİNDE ince kontrol (girdi geçse bile).

Neden: input_guard girdiyi geçirse bile (kalıp listesi kaçırdığında, ya da
retrieval'in getirdiği kaynak metninin kendisi sorunlu bir alıntı içerdiğinde)
LLM'in ÜRETTİĞİ cevap zararlı olabilir. Bu modül, generator.py'da LLM
çağrısından SONRA zararlı-içerik kalıplarını üretilen metne karşı çalıştırır.

AUDIT EXP-007 (#O1): girdi self-harm kalıbı ("kendi(me|ne) ... zarar") 3. ŞAHIS
eğitim içeriğini de yakalıyor ("sigara kişinin kendine zarar vermesine yol açar")
→ ÇIKTIDA bu yanlış-pozitif meşru sağlık/biyoloji cevabını bloklar. Bu yüzden
ÇIKTI için self-harm'i DAR (1. şahıs NİYET) kalıpla ölçeriz; diğer kategoriler
(şiddet/uyuşturucu/cinsel/nefret) girdiyle aynı kalır. input_guard NOT'u geçerli:
regex tabanlı, TEK savunma değil (defense-in-depth)."""
from __future__ import annotations

import re

from .input_guard import GuardVerdict, _HARM_CATEGORIES, _fold_loose

_OUTPUT_REFUSE_MESSAGE = (
    "Üretilen cevap güvenlik kontrolünden geçemedi; bu soruyu şu an "
    "cevaplayamıyorum. Lütfen farklı bir şekilde sor."
)

# Çıktı için DAR self-harm: 1. şahıs niyet/eylem YA DA INSTRUKSİYONEL kendine-zarar
# ("kendine zarar vermenin YOLU/YÖNTEMİ", "kendine NASIL zarar"). 3. şahıs BETİMSEL
# ("sigara kendine zarar verir", "... vermesine yol açar") HARİÇ — method sözcüğü
# (yolu/yöntem/nasıl/tarif/adım) ararız; "yol açar" (bare yol) eşleşmez (AUDIT #O1).
_OUTPUT_SELF_HARM = re.compile(
    r"kendi(?:mi|me)\b.{0,15}(?:öldür|kes\b|yarala)"                        # 1. şahıs eylem
    r"|kendi(?:me|mi|ne)\b.{0,25}zarar.{0,18}(?:yol(?:u|ları|lar[ıi]|un)|yöntem|nasıl|tarif|adım)"  # instruksiyonel
    r"|kendi(?:me|mi|ne)\b.{0,10}nasıl.{0,15}zarar"                         # "kendine nasıl zarar"
    r"|intihar (?:et|nasıl|yöntem|edeceğim)|canıma kıy|hayatıma son ver|kendimi öldür"
    r"|kill myself|hurt myself|end my life"
)


def check_output(text: str | None) -> GuardVerdict:
    """Üretilen cevap metnini zararlı-içerik kalıplarına karşı kontrol eder.
    Boş/None -> allow. self-harm ÇIKTIDA dar (1. şahıs) kalıpla; diğer kategoriler
    girdiyle aynı. injection BURADA taranmaz (çıktı kullanıcıya yönelik istek değil)."""
    if not text or not text.strip():
        return GuardVerdict(action="allow", category="", message="", score=0.0)

    folded = _fold_loose(text)
    for cat, patterns, _ in _HARM_CATEGORIES:
        pats = [_OUTPUT_SELF_HARM] if cat == "self_harm" else patterns
        if any(p.search(folded) for p in pats):
            return GuardVerdict(action="refuse", category=cat,
                                message=_OUTPUT_REFUSE_MESSAGE, score=1.0)
    return GuardVerdict(action="allow", category="", message="", score=0.0)
