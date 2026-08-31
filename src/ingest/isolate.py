"""Faz 0.4 — Sızıntı izolasyonu (retrieval indeksinden ne çıkarılmalı).

Literatürün en vurguladığı kural: soru/cevap-anahtarı/meta içerik retrieval'a
GİRMEMELİ; yoksa ölçülen akıl yürütme değil, **cevap sızıntısıdır** ([[benchmark]]
güvenlik kapısı: yasaklı retrieval = 0).

Gerçek 12-bio bulgusu:
- Cevap anahtarı büyük ölçüde **QR kod arkasında** (metinde yok) → sızıntı düşük.
- İzole edilecekler: **ön/arka-madde sayfaları** (içindekiler, kitap tanıtımı,
  kaynakça, sözlük, cevap-anahtarı başlıklı) + **dağınık değerlendirme-soru blokları**
  ("Değerlendirme Soruları", "Ölçme ve Değerlendirme", çoktan-seçmeli A)-E) blokları).

0.4a: sayfa düzeyi meta/arka-madde izolasyonu (başlık işaretine göre, yüksek kesinlik).
0.4b: blok düzeyi soru/değerlendirme izolasyonu (öğretici metni sayfada korur).
"""
from __future__ import annotations
import re

from .pdf_parse import ParsedDoc, HEADING, HEADER

# --- 0.4a: sayfa-düzeyi meta/arka-madde başlık işaretleri ---
_PAGE_MARKERS = {
    "içindekiler": "icindekiler",
    "kitap tanıtımı": "kitap_tanitimi",
    "kaynakça": "kaynakca",
    "kaynaklar": "kaynakca",
    "sözlük": "sozluk",
    "cevap anahtarı": "cevap_anahtari",
    "dizin": "dizin",
}

# --- 0.4b: blok-düzeyi değerlendirme/soru işaretleri ---
_ASSESS_MARKERS = (
    "değerlendirme soruları", "ölçme ve değerlendirme", "öz değerlendirme",
    "ünite değerlendirme", "boşluk doldurma soru", "açık uçlu soru",
    "çoktan seçmeli soru", "doğru-yanlış", "aşağıdaki soruları",
)
_OPTION = re.compile(r"(?<![A-Za-zÇĞİÖŞÜ])[A-E]\)")


def _norm(s: str) -> str:
    # TR-güvenli küçültme (İ→i, I→ı) — aksi halde "KİTAP".lower() combining-dot üretir
    # ve "kitap" ile eşleşmez. Tam NFC normalizasyon 0.6'da (tr_normalize).
    return s.replace("İ", "i").replace("I", "ı").lower().strip()


def page_exclusion_reason(page) -> str | None:
    """Sayfa tamamen meta/arka-madde mi? Yalnız HEADER/HEADING bloğunda işaret
    aranır (gövdede geçen 'cevap anahtarı' → içindekiler yanlış-pozitifini önler)."""
    for b in page.blocks:
        if b.kind not in (HEADER, HEADING):
            continue
        t = _norm(b.text)
        for marker, reason in _PAGE_MARKERS.items():
            if marker in t:
                return reason
    return None


def block_is_assessment(text: str) -> bool:
    t = _norm(text)
    return any(m in t for m in _ASSESS_MARKERS)


def block_is_question_options(text: str) -> bool:
    """Çoktan seçmeli soru bloğu: ≥3 farklı A)-E) şık işareti."""
    opts = set(_OPTION.findall(text))
    return len(opts) >= 3


def apply_isolation(doc: ParsedDoc) -> dict:
    """doc'u yerinde işaretle (block.retrieval_disi) + özet rapor döndür.
    Sayfa hariçse o sayfanın TÜM blokları; ayrıca dağınık soru/değerlendirme blokları."""
    excluded_pages: list[dict] = []
    page_excl_blocks = 0
    assess_blocks = 0
    for page in doc.pages:
        reason = page_exclusion_reason(page)
        if reason:
            for b in page.blocks:
                b.retrieval_disi = True
            page_excl_blocks += len(page.blocks)
            excluded_pages.append({"page": page.number, "reason": reason})
            continue
        for b in page.blocks:
            if block_is_assessment(b.text) or block_is_question_options(b.text):
                b.retrieval_disi = True
                assess_blocks += 1
    total_blocks = sum(len(p.blocks) for p in doc.pages)
    excluded = sum(1 for p in doc.pages for b in p.blocks if b.retrieval_disi)
    return {
        "excluded_pages": excluded_pages,
        "excluded_page_count": len(excluded_pages),
        "page_level_excluded_blocks": page_excl_blocks,
        "assessment_excluded_blocks": assess_blocks,
        "total_blocks": total_blocks,
        "excluded_blocks": excluded,
        "retrievable_blocks": sum(1 for p in doc.pages for b in p.blocks if b.retrievable),
    }
