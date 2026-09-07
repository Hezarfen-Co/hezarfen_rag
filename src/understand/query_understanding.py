"""Faz — Sorgu anlama (#14 S7): intent sınıflandırma + varlık (NER) çıkarımı.

Deterministik (kural/regex tabanlı, LLM YOK) — hızlı, ücretsiz, açıklanabilir.
TR-güvenli eşleşme (`fold_for_match`: İ/ı doğru). Amaç: (a) intent'e göre yönlendirme
(ör. 'özet' isteği → Summarizer; 'sohbet'/kapsam-dışı → erken çekimser), (b) NER ile
sorgunun anahtar terimlerini görünür kılmak (retrieval hata-ayıklama + gelecekte
sorgu-genişletme). Rewrite (çok-turlu) ZATEN src/memory'de; bu modül onu tamamlar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from ..text.tr_normalize import fold_for_match


class Intent(str, Enum):
    KARSILASTIRMA = "karsilastirma"   # fark/benzerlik/kıyas
    NEDEN_SONUC = "neden_sonuc"       # neden/niçin/sebep
    HESAPLAMA = "hesaplama"           # kaç/hesapla/bul (sayısal)
    LISTE = "liste"                   # nelerdir/say/listele
    ORNEK = "ornek"                   # örnek ver
    OZET = "ozet"                     # özetle/özet çıkar
    TANIM = "tanim"                   # nedir/ne demek/tanımı
    ACIKLAMA = "aciklama"            # nasıl/açıkla
    SOHBET = "sohbet"                 # selam/teşekkür/kapsam-dışı sohbet
    DIGER = "diger"


# Öncelik SIRALI (spesifik → genel): karşılaştırma "DNA ile RNA farkı nedir"de
# 'nedir'den (tanım) ÖNCE gelmeli. fold_for_match sonrası eşleşir.
_INTENT_RULES: list[tuple[Intent, list[str]]] = [
    (Intent.SOHBET, [r"\bselam\b", r"\bmerhaba\b", r"nasılsın", r"teşekkür", r"günaydın",
                     r"iyi misin", r"kim yaptın|seni kim"]),
    (Intent.OZET, [r"özetle", r"özet çıkar", r"özetini", r"kısaca özet", r"\bözet\b"]),
    (Intent.KARSILASTIRMA, [r"karşılaştır", r"\bfark[ıi]?\b", r"farkları", r"benzerlik",
                            r"arasındaki fark", r"\bile\b.*\barasında", r"hangisi daha"]),
    (Intent.NEDEN_SONUC, [r"\bneden\b", r"\bniçin\b", r"niye\b", r"sebeb", r"yol açar",
                          r"sonucu (?:ne|nedir)"]),
    (Intent.HESAPLAMA, [r"\bkaç\b", r"hesapla", r"kaçtır", r"ne kadar", r"yüzde kaç",
                        r"kaç mol", r"kaç gram"]),
    (Intent.LISTE, [r"nelerdir", r"nelerdir\b", r"listele", r"say(?:ar mısın)?\b",
                    r"maddeler", r"çeşitleri", r"türleri", r"kaç tür"]),
    (Intent.ORNEK, [r"örnek ver", r"örnek(?:ler)? (?:nedir|neler)", r"bir örnek"]),
    (Intent.TANIM, [r"\bnedir\b", r"ne demek", r"tanımı", r"ne anlama"]),
    (Intent.ACIKLAMA, [r"\bnasıl\b", r"açıkla", r"anlat", r"nasıl (?:olur|çalışır|gerçekleşir)"]),
]


def classify_intent(query: str | None) -> Intent:
    """Sorgunun birincil intent'i (öncelik-sıralı ilk eşleşen kural)."""
    if not query or not query.strip():
        return Intent.DIGER
    folded = fold_for_match(query)
    for intent, pats in _INTENT_RULES:
        for p in pats:
            if re.search(p, folded):
                return intent
    return Intent.DIGER


# NER: büyük harfle başlayan çok-sözcüklü özel terimler (Watson-Crick), TÜM-BÜYÜK
# kısaltmalar (DNA, ATP, RNA), tırnaklı terimler, kimyasal formül-benzeri (H2O, CO2).
_ACRONYM = re.compile(r"\b[A-ZÇĞİÖŞÜ]{2,}(?:\d+)?\b")
_FORMULA = re.compile(r"\b[A-Z][a-z]?\d+(?:[A-Z][a-z]?\d*)*\b")     # H2O, CO2, KMnO4
_QUOTED = re.compile(r"[\"'“”]([^\"'“”]{2,40})[\"'“”]")
_PROPER = re.compile(r"\b[A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:[- ][A-ZÇĞİÖŞÜ][a-zçğıöşü]+)+\b")  # Watson-Crick, Kepler Kanunları

# soru kalıbı/dolgu sözcükleri — NER'de terim sayılmaz
_STOP = {"Nedir", "Nasıl", "Neden", "Niçin", "Hangi", "Kaç", "Bir", "Bu", "Şu"}


def extract_entities(query: str | None) -> list[str]:
    """Sorgudaki aday anahtar terimler (kısaltma/formül/özel-ad/tırnaklı). Sıra
    korunur, tekrarsız. Deterministik; yanlış-pozitife toleranslı (retrieval yardımcı)."""
    if not query:
        return []
    ents: list[str] = []
    def _add(x):
        x = x.strip()
        if x and x not in _STOP and x not in ents:
            ents.append(x)
    for m in _QUOTED.findall(query):
        _add(m)
    for m in _PROPER.findall(query):
        _add(m)
    for m in _FORMULA.findall(query):
        _add(m)
    for m in _ACRONYM.findall(query):
        if len(m) <= 6:                    # DNA/ATP/RNA/mRNA... çok uzunsa muhtemelen cümle-başı değil
            _add(m)
    return ents


@dataclass
class QueryAnalysis:
    intent: Intent
    entities: list[str] = field(default_factory=list)
    is_out_of_scope: bool = False         # sohbet/selam → retrieval'a gitmeye gerek yok
    wants_summary: bool = False


def analyze(query: str | None) -> QueryAnalysis:
    intent = classify_intent(query)
    return QueryAnalysis(intent=intent, entities=extract_entities(query),
                         is_out_of_scope=(intent == Intent.SOHBET),
                         wants_summary=(intent == Intent.OZET))
