"""Özet çıkarma promptu — extract-then-abstract, DETAYLI + atıflı ("kanıtlı özet").

Soru-cevap promptundan (src/generate/prompt.py) FARKI: burada bir SORU yok —
verilen KAYNAK bölümlerinin TAMAMINI kapsayan, alt-başlıklarla yapılandırılmış,
DETAYLI bir özet istenir (yüzeysel özet DEĞİL). `[N]` numaraları summarizer.py'da
gerçek birime (span_id + sayfa) bağlanır ("kaynak yer bulma", mimari §0.1 —
generator.py'daki desenle TUTARLI).
"""
from __future__ import annotations

# Kaynaklarda özetlenecek ilgili içerik YOKSA modelin yazması gereken TAM cümle
# (summarizer.py'nin post-hoc/FAIL-CLOSED karşılaştırmaları bu sabitten türer).
NO_CONTENT_SENTENCE = "Bu bölümde özetlenecek yeterli içerik bulunamadı."

SYSTEM_PROMPT = f"""Sana verilen numaralı KAYNAK bölümlerinden DETAYLI, yapılandırılmış \
bir özet çıkar. Yalnız kaynaklardaki bilgiyi kullan (uydurma yok). Özeti \
alt-başlıklarla düzenle; her önemli bilgi cümlesinin sonuna dayandığı kaynak \
numarasını [N] ekle. Türkçe, öğrenci-anlaşılır, ama DETAYLI (yüzeysel değil) — \
önemli tanımlar, mekanizmalar, örnekler, ilişkiler dahil. Kaynaklarda yoksa \
"{NO_CONTENT_SENTENCE}" de."""


def build_summary_prompt(units_text_blocks: list[dict], scope_label: str = "") -> tuple[str, str]:
    """Numaralı kaynak blokları + kapsam etiketi -> (system, user) prompt çifti.

    `units_text_blocks`: [{"n": int, "page": <int|str|None>, "text": str}, ...]
    Her biri "[Kaynak N | s.<sayfa>]\\n<metin>" biçiminde numaralanır
    (generator.py'daki `numbered_sources` desenle TUTARLI — sayfa yoksa "?").
    `scope_label`: insan-okunur kapsam açıklaması (ör. "s.10-25"); boşsa atlanır.
    """
    blocks = []
    for b in units_text_blocks:
        page = b.get("page")
        page_str = str(page) if page not in (None, "") else "?"
        blocks.append(f"[Kaynak {b['n']} | s.{page_str}]\n{b['text']}")
    sources_block = "\n\n".join(blocks)

    scope_line = f"KAPSAM: {scope_label}\n\n" if scope_label else ""
    user = f"{scope_line}KAYNAKLAR:\n{sources_block}\n\nÖZET:"
    return SYSTEM_PROMPT, user
