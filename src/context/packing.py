"""Faz — Context engineering: token bütçeleme + lost-in-the-middle sıralama.

RES-003 §2-3 + "3 ilke: daha çok context ≠ daha iyi". İki deterministik adım
(LLM YOK, saf mantık) rerank_select çıktısına (RerankedContext listesi, skor
azalan) uygulanır:

1. **Token bütçesi:** toplam bağlam token'ını sınırla (DeepSeek giriş maliyeti +
   context sığdırma). En yüksek skorlu context'ler tutulur; bütçeyi aşınca en
   düşük skorlular DÜŞÜRÜLÜR. En az 1 context her zaman kalır (fail-closed eşiği
   zaten Generator'da; buraya gelen context alakalı sayılır).
2. **Lost-in-the-middle:** modeller uzun bağlamın ORTASINDAKİ bilgiyi unutur
   (Liu 2023). En güçlü kanıtları BAŞA ve SONA, zayıfları ORTAYA yerleştir.

Atıf/span değişmez — yalnız SIRA + hangi context'lerin dahil edildiği değişir.
"""
from __future__ import annotations

from ..chunk.chunker import approx_tokens


def _ctx_text(ctx) -> str:
    """Bir context'in token maliyetine sayılan metni (child + varsa parent)."""
    text = getattr(ctx, "text", "") or ""
    parent = getattr(ctx, "parent_text", None)
    if parent and parent.strip() and parent.strip() != text.strip():
        text = f"{text}\n\n{parent}"
    return text


def apply_token_budget(contexts, max_tokens: int):
    """Skor-azalan `contexts`'i toplam token bütçesine göre kırp. En yüksek
    skorlular tutulur; bütçeyi aşan düşük-skorlular düşer. En az 1 context kalır.
    contexts zaten skor-azalan gelir (rerank_select). Sırayı KORUR."""
    if not contexts:
        return []
    kept, used = [], 0
    for ctx in contexts:
        t = approx_tokens(_ctx_text(ctx))
        if kept and used + t > max_tokens:      # ilk context'i her zaman al;
            continue                            # sonrakinde bütçeyi aşanı ATLA ama
        kept.append(ctx)                        # SONRAKİ (sığan) düşük-skorluları DENE
        used += t                               # (AUDIT #M3: eski `break` sığanları da düşürüyordu)
    return kept


def reorder_lost_in_middle(contexts):
    """Skor-azalan listeyi 'en güçlü uçlara, zayıf ortaya' düzenine çevir.
    Örn. skor sırası [A,B,C,D,E] -> [A,C,E,D,B] (A başta, B sonda; en zayıf D/C orta).
    Yöntem: sırayla en güçlüyü BAŞA, sonrakini SONA ekle (deque-benzeri)."""
    if len(contexts) <= 2:
        return list(contexts)
    head, tail = [], []
    for i, ctx in enumerate(contexts):
        (head if i % 2 == 0 else tail).append(ctx)
    return head + tail[::-1]


def pack_contexts(contexts, *, max_tokens: int = 8000, reorder: bool = True):
    """Bütçe + (opsiyonel) lost-in-the-middle sıralama. Generator bunu
    rerank_select'ten SONRA, numaralı kaynakları kurmadan ÖNCE çağırır."""
    packed = apply_token_budget(contexts, max_tokens)
    if reorder:
        packed = reorder_lost_in_middle(packed)
    return packed
