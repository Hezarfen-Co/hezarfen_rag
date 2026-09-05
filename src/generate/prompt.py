"""Faz 1.7a — kaynak-sınırlı üretim promptu (grounded generation).

Amaç: LLM'i YALNIZ getirilen kaynaklarla sınırlamak + her iddiayı `[N]` ile
atıflandırmak. `[N]` numaraları generator.py'da gerçek kaynağa (chunk_id +
span_ids + sayfa + bbox) bağlanır ("kaynak yer bulma", mimari §0.1: cevap ham
leaf span'lara bağlı). Kanıt yetersizse LLM hiç çağrılmaz (bkz. generator.py
FAIL-CLOSED); bu prompt yalnız LLM ÇAĞRILDIĞINDA kullanılır.
"""
from __future__ import annotations

# Post-hoc abstain algılama (generator.py), model çağrısından SONRA cevabı bu
# cümleyle karşılaştırır — bire bir aynı sabitten türetildiği için prompt ile
# karşılaştırma her zaman senkron kalır.
ABSTAIN_SENTENCE = "Kaynaklarda bu bilgi bulunamadı."

SYSTEM_PROMPT = f"""Sen bir eğitim asistanısın. Yalnızca aşağıda verilen KAYNAKLAR'dan \
yararlanarak Türkçe cevap ver. Kaynaklarda yer almayan hiçbir bilgi uydurma.

Kurallar:
- Her cümlenin sonuna, o cümlenin dayandığı kaynağın numarasını köşeli parantez \
içinde ekle: [1], [2] gibi. Birden çok kaynağa dayanıyorsa hepsini yaz: [1][3].
- Yalnız verilen kaynaklardaki bilgiyi kullan; kaynaklarda olmayan hiçbir şeyi \
ekleme, tahmin etme veya genelleme yapma.
- Sorunun cevabı kaynaklarda yoksa veya kaynaklar yetersizse, tam olarak şunu \
yaz: "{ABSTAIN_SENTENCE}"
- Üçüncü tekil şahıs kullan (örn. "hücre ... içerir"; "ben/biz/sen" kullanma).
- Kısa ve öz cevap ver; kaynak metnini olduğu gibi kopyalama, kendi cümlelerinle \
özetle ama anlamı değiştirme."""


def build_grounded_prompt(query: str, sources: list[dict]) -> tuple[str, str]:
    """query + numaralı kaynaklar → (system, user) prompt çifti.

    sources: [{"n": int, "ders": str, "page": str, "text": str}, ...]
    Her kaynak "[Kaynak N | <ders> s.<sayfa>]\\n<metin>" biçiminde numaralanır
    (generator.py sayfayı span_meta'dan çıkarıp burada hazır string verir).
    """
    blocks = []
    for s in sources:
        ders = s.get("ders") or ""
        page = s.get("page") or "?"
        blocks.append(f"[Kaynak {s['n']} | {ders} s.{page}]\n{s['text']}")
    sources_block = "\n\n".join(blocks)
    user = f"KAYNAKLAR:\n{sources_block}\n\nSORU: {query}\n\nCEVAP:"
    return SYSTEM_PROMPT, user
