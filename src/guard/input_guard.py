"""Faz 1.7b — girdi guardrail: zararlı-içerik + prompt-injection tespiti.

Neden (RES-002 §2 — RagArt analizi): RagArt'ta zararlı/toksik/kendine-zarar
filtresi YOKTU (girdi+çıktı); reşit-olmayan öğrenci kitlesi için bu kabul
edilemezdi. Rol yetkisi de client-header'dan geliyordu (herhangi istemci
açabilirdi) — BİZDE rol yetkisi SUNUCU-TARAFI türevlidir (bkz. roles.py),
bu modülün konusu DEĞİL; bu modül yalnız İÇERİK güvenliğine bakar.

Yöntem: regex/kalıp tabanlı kara-liste (Türkçe + İngilizce), TR-normalize
(`fold_for_match`) ile eşleştirilir — İ/ı büyük-küçük harf ve görünmez
karakter varyantlarına dayanıklı (aksan KORUNUR, bkz. src/text/tr_normalize.py).

*** NOT (dürüstçe sınır): bu regex/kalıp tabanlı bir filtredir, TEK savunma
KATMANI DEĞİLDİR. ***  Parafraz, homoglyph (görsel olarak benzer ama farklı
Unicode karakter), base64/rot13 kodlama, dolaylı ifade ("bir arkadaşım
kendine nasıl zarar verir" gibi 3. şahıs kaçamağı) ile KOLAYCA atlatılabilir
— RagArt'ın salt-regex injection filtresi de aynı zaafı taşıyordu (RES-002
§2). İleride LLM-tabanlı güvenlik sınıflandırıcı (ör. ayrı ucuz model ile
ikili sınıflandırma) eklenecek; bunun tetikleyicisi golden-set/eval'in bu
kalıp listesinin kaçırdığı örnekleri göstermesi olacak (bkz. OPTIMIZATION.md
§A, G.3). Bu dosya, güvenlik iddiası değil, İLK SAVUNMA HATTI'dır.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..text.tr_normalize import fold_for_match


@dataclass
class GuardVerdict:
    """Guard kararı. `score` KABA bir güven göstergesidir (regex-eşleşme
    tabanlı: eşleşme varsa 1.0, yoksa 0.0) — olasılıksal bir sınıflandırıcı
    SKORU DEĞİLDİR (bkz. dosya başı NOT)."""
    action: str            # "allow" | "refuse"
    category: str = ""     # "" (allow) | "self_harm" | "violence_weapons" |
                           # "sexual_content" | "illegal_drugs" |
                           # "hate_harassment" | "prompt_injection"
    message: str = ""      # refuse ise: yaşa-uygun red mesajı (+ güvenli yönlendirme)
    score: float = 0.0


def _compile(patterns: list[str]) -> list[re.Pattern]:
    # 'ı' (dotless) -> 'i' (dotted) HEM kalıpta HEM eşleşme metninde uygulanır
    # (bkz. `_fold_loose`) — ASCII-only klavye/otomatik-düzeltme genelde
    # Türkçe "İ" yerine düz ASCII "I" yazar; `fold_for_match` bunu (doğru TR
    # kuralına göre) dotless "ı"ya çevirir ve "intihar" gibi kelimeler
    # "ıntihar" olur, kalıpla eşleşmez. Güvenlik-kritik bir filtrede
    # kaçırmaktansa (yanlış-negatif) biraz daha geniş eşleşmeyi (yanlış-
    # pozitif) TERCİH EDERİZ — bu yüzden ı/i ayrımı kalıp eşleştirmede
    # kasıtlı olarak ORTADAN KALDIRILIR.
    return [re.compile(p.replace("ı", "i")) for p in patterns]


def _fold_loose(s: str) -> str:
    """`fold_for_match` + ı/i birleştirme (bkz. `_compile` NOT)."""
    return fold_for_match(s).replace("ı", "i")


# ---------------------------------------------------------------------------
# Zararlı-içerik kalıpları (Türkçe + İngilizce), kategori bazlı.
# fold_for_match SONRASI metne uygulanır: TR-doğru küçültme (İ->i, I->ı) +
# NFC + görünmez-karakter temizliği yapılmış; aksan/İngilizce harfler AYNEN
# kalır. Kalıplar KASITLI OLARAK dar/spesifik tutuldu (ör. yalnız "zarar"
# değil "kendime ... zarar") — aksi halde biyoloji/tarih gibi masum eğitim
# sorularında (ör. "hücreye zarar veren etmenler", "savaşta kim öldü") YANLIŞ
# POZİTİF üretir (bkz. testler: "masum eğitim sorusu").
# ---------------------------------------------------------------------------

_SELF_HARM_PATTERNS = [
    # Türkçe
    # genel yakalayıcı: "kendime/kendimi/kendine" + (kısa aralık) + "zarar" —
    # hem 1. şahıs soru biçimini ("kendime nasıl zarar veririm") HEM 3. şahıs/
    # betimsel biçimi ("kendine zarar vermenin bir yolu") yakalar (bkz.
    # output_guard testi: model çıktısı 3. şahıs anlatır).
    r"kendi(?:me|mi|ne)\b.{0,15}zarar",
    r"kendimi nasıl (?:kes|yarala)",
    r"kendimi yaralamak istiyorum",
    r"intihar (?:etmek|etsem|nasıl|yöntem|düşünüyorum|düşüncesi)",
    r"canıma kıymak istiyorum",
    r"kendimi öldürmek istiyorum",
    r"hayatıma son vermek istiyorum",
    r"yaşamak istemiyorum",
    r"ölmek istiyorum",
    # İngilizce
    r"kill myself",
    r"hurt myself",
    r"self[ -]?harm",
    r"\bsuicide\b",
    r"want to die",
    r"end my life",
]

_VIOLENCE_WEAPONS_PATTERNS = [
    # Türkçe
    r"bomba nasıl yapılır",
    r"silah nasıl yapılır",
    r"patlayıcı nasıl yapılır",
    r"birini nasıl öldürürüm",
    r"birini öldürmek istiyorum",
    r"nasıl bıçaklarım",
    # İngilizce
    r"how to make a bomb",
    r"how to make a gun",
    r"how to (?:make|build) explosives",
    r"how (?:do i|to) kill (?:someone|a person)",
]

_SEXUAL_CONTENT_PATTERNS = [
    # Türkçe
    r"cinsel ilişki nasıl",
    r"\bporno\b",
    r"çıplak (?:resim|fotoğraf|foto)",
    r"müstehcen içerik",
    # İngilizce
    r"\bporn\b",
    r"sexual intercourse",
    r"nude (?:photo|picture|pic)",
]

_ILLEGAL_DRUGS_PATTERNS = [
    # Türkçe
    r"uyuşturucu nasıl (?:yapılır|elde edilir|temin edilir|kullanılır)",
    r"esrar nasıl (?:yapılır|kullanılır|elde edilir)",
    r"eroin nasıl (?:yapılır|kullanılır)",
    r"nereden uyuşturucu (?:bulurum|alırım)",
    r"metamfetamin nasıl (?:yapılır|üretilir)",
    # İngilizce
    r"how to make (?:meth|methamphetamine|drugs)",
    r"buy drugs online",
    r"how to get high on",
]

_HATE_HARASSMENT_PATTERNS = [
    # Türkçe
    r"aşağılık (?:ırk|millet|din)",
    r"seni (?:öldüreceğim|geberteceğim)",
    r"defol (?:ülkeden|ülkemizden)",
    r"hepsi(?:ni)? öldürmeli",
    # İngilizce
    r"i hate all \w+",
    r"kill all \w+",
    r"go back to your (?:country|own country)",
]

_SELF_HARM_MESSAGE = (
    "Bu konuda sana yardımcı olamam. Eğer kendine zarar verme ya da hayatına "
    "son verme gibi düşüncelerin varsa lütfen hemen güvendiğin bir yetişkinle "
    "(ailen, öğretmenin ya da okulunun rehberlik servisi) konuş. Acil bir "
    "durumdaysan 112'yi ara. Yalnız değilsin; yardım isteyebilirsin."
    # NOT: kriz-hattı numaraları (ör. sosyal destek hattı) kasıtlı olarak
    # sabit KODLANMADI — yanlış/güncel-olmayan bir kriz hattı numarası
    # yayınlamak yüksek risk taşır. Üretime çıkmadan önce Kadir güncel ve
    # doğrulanmış bir yerel destek hattı numarası eklemeli/onaylamalı.
)

_VIOLENCE_WEAPONS_MESSAGE = (
    "Bu konuda sana yardımcı olamam; şiddet, silah ya da patlayıcı yapımıyla "
    "ilgili bilgi veremem. Güvenliğinle ilgili bir endişen varsa bir "
    "yetişkinle konuş ya da acil durumda 112'yi ara."
)

_SEXUAL_CONTENT_MESSAGE = (
    "Bu konu bu uygulamanın kapsamı ve yaş grubunun dışında; bu tür bir "
    "soruya cevap veremem. Bu konularda bir yetişkinle (ailen, öğretmenin "
    "ya da okul rehberlik servisi) konuşman daha uygun olur."
)

_ILLEGAL_DRUGS_MESSAGE = (
    "Uyuşturucu veya yasadışı maddelerle ilgili bilgi veremem. Bu konuda bir "
    "endişen varsa bir yetişkinle ya da okulunun rehberlik servisiyle "
    "konuşabilirsin."
)

_HATE_HARASSMENT_MESSAGE = (
    "Nefret söylemi, tehdit ya da taciz içeren isteklere yardımcı olamam. "
    "Birine ya da bir gruba zarar verme niyetin varsa lütfen bir yetişkinle "
    "konuş."
)

_INJECTION_MESSAGE = (
    "Bu isteği yerine getiremem; yalnızca ders kaynaklarına dayalı sorularına "
    "yardımcı olabilirim."
)

# Öncelik SIRALI: kendine-zarar hayati risk taşıdığı için İLK kontrol edilir
# (bir sorguda birden çok kategori kalıbı eşleşirse en kritik olan raporlanır).
_HARM_CATEGORIES: list[tuple[str, list[re.Pattern], str]] = [
    ("self_harm", _compile(_SELF_HARM_PATTERNS), _SELF_HARM_MESSAGE),
    ("violence_weapons", _compile(_VIOLENCE_WEAPONS_PATTERNS), _VIOLENCE_WEAPONS_MESSAGE),
    ("illegal_drugs", _compile(_ILLEGAL_DRUGS_PATTERNS), _ILLEGAL_DRUGS_MESSAGE),
    ("sexual_content", _compile(_SEXUAL_CONTENT_PATTERNS), _SEXUAL_CONTENT_MESSAGE),
    ("hate_harassment", _compile(_HATE_HARASSMENT_PATTERNS), _HATE_HARASSMENT_MESSAGE),
]

_HARM_MESSAGES: dict[str, str] = {cat: msg for cat, _, msg in _HARM_CATEGORIES}


def _scan_harm_categories(text: str) -> str | None:
    """Fold edilmiş metni tüm zararlı-içerik kategorilerine karşı tarar;
    ilk (öncelik sıralı) eşleşen kategori adını döner, yoksa None.
    input_guard VE output_guard tarafından PAYLAŞILIR (aynı kalıp listesi)."""
    folded = _fold_loose(text)
    for category, patterns, _ in _HARM_CATEGORIES:
        for pat in patterns:
            if pat.search(folded):
                return category
    return None


# ---------------------------------------------------------------------------
# Prompt-injection kalıpları (RES-002 §2'den esinli — RagArt'ta TR'de 8 kalıp,
# eşik 0.5 idi). TEKRAR: bu kalıp listesi TEK savunma DEĞİLDİR (dosya başı NOT).
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = _compile([
    # Türkçe
    r"önceki talimatları (?:yok say|unut)",
    r"yukarıdaki talimatları (?:yok say|görmezden gel)",
    r"sistem promptunu (?:göster|yazdır|ifşa et|paylaş)",
    r"kurallarını unut",
    r"gizli talimatlarını (?:göster|söyle|paylaş)",
    r"artık (?:hiç|bir)? ?kısıtlaman yok",
    # İngilizce
    r"ignore (?:the )?(?:previous|above|all)(?: prior)? instructions",
    r"disregard (?:your|the|all) (?:rules|instructions)",
    r"reveal (?:your |the )?system prompt",
    r"\bjailbreak\b",
    r"do anything now",
    r"pretend (?:you are|to be) (?:an ai )?(?:with no|without) restrictions",
])


def check_input(query: str | None) -> GuardVerdict:
    """Kullanıcı sorgusunu zararlı-içerik + prompt-injection kalıplarına karşı
    kontrol eder. Boş/None sorgu -> allow (zararsız, içerik yok). Kalıp
    eşleşirse -> refuse + yaşa-uygun red mesajı + kategori.

    Öncelik: zararlı-içerik (hayati/güvenlik riski) ÖNCE, injection SONRA —
    karışık bir sorguda (eğitim + zararlı) zararlı-içerik kazanır (safety-first)."""
    if not query or not query.strip():
        return GuardVerdict(action="allow", category="", message="", score=0.0)

    category = _scan_harm_categories(query)
    if category is not None:
        return GuardVerdict(action="refuse", category=category,
                            message=_HARM_MESSAGES[category], score=1.0)

    folded = _fold_loose(query)
    for pat in _INJECTION_PATTERNS:
        if pat.search(folded):
            return GuardVerdict(action="refuse", category="prompt_injection",
                                message=_INJECTION_MESSAGE, score=1.0)

    return GuardVerdict(action="allow", category="", message="", score=0.0)
