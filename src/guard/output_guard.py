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
# #44 (EXP-010/SEC-04): `kendini`/`kendin` bicimi alternasyonda YOKTU -> model
# ciktisindaki yontem anlatimi 3/3 ALLOW aliyordu ("Bir kisi kendini oldurmek
# isterse en yaygin yontem...", "Kendini asmanin adimlari sunlardir",
# "Bilek kesmek icin jilet kullanilir..."). Govde genisletildi + yontem
# sozlugu eklendi. 3. sahis BETIMSEL ("sigara kendine zarar verir") HARIC
# kalmaya devam ediyor: instruksiyonel isaret (yol/yontem/nasil/adim/tarif)
# ya da acik yontem sozcugu araniyor (AUDIT #O1 yanlis-pozitifi korunur).
_OUTPUT_SELF_HARM = re.compile(
    r"kendi(?:mi|me|ni|n)\b.{0,15}(?:öldür|as(?:mak|arak|ma\w*)|kes\b|yarala)"   # eylem
    r"|kendi(?:me|mi|ne|ni|n)\b.{0,25}zarar.{0,18}(?:yol(?:u|ları|lar[ıi]|un)|yöntem|nasıl|tarif|adım)"
    r"|kendi(?:me|mi|ne|ni|n)\b.{0,10}nasıl.{0,15}zarar"
    r"|intihar (?:et|nasıl|yöntem|edeceğim)|canıma kıy|hayatıma son ver|kendimi öldür"
    # yontem anlatimi (kendi* govdesi olmadan da): kesme/doz/asma/atlama
    r"|bilek\s*kes(?:me|mek|erek)"
    r"|(?:jilet|bıçak|usturayla?)\b.{0,25}(?:damar|bilek)"
    r"|(?:ölümcül|öldürücü|letal)\s*(?:ilaç\s*)?doz"
    r"|aşırı\s*doz.{0,25}(?:öl(?:üm|ür)|ölümcül)"
    r"|(?:ip(?:le|e)?|iple)\s*(?:kendini|kendimi|boyn)"
    r"|(?:balkondan|köprüden|camdan|yüksekten)\s*atla(?:mak|yarak|r)?\b.{0,25}öl"
    r"|acısız\s*(?:ölüm|intihar)"
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
