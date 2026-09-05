"""Faz — sliding-window konuşma durumu (hafif, stateless).

Son N turu tutar; üretim promptuna kısa geçmiş bağlamı (tutarlılık için) verir.
Sunucu-tarafı/stateless: geçmiş her istekte çağıran katmandan gelir (RES-003 §3;
uzun sohbet için summary/vector hafıza sonraki adım). Asıl çok-turlu doğruluk
`history_rewrite`'tadır; bu yalnız üslup/tutarlılık bağlamıdır."""
from __future__ import annotations


def sliding_window(history, max_turns: int = 6):
    """Geçmişin son `max_turns` turunu döndür (FIFO). Boş/None -> []."""
    if not history:
        return []
    return list(history[-max_turns:]) if max_turns else list(history)


def window_context(history, max_turns: int = 6) -> str:
    """Son turları 'Kullanıcı: ... / Asistan: ...' biçiminde kısa metin bağlamı."""
    turns = sliding_window(history, max_turns)
    lines = []
    for t in turns:
        role = t.get("role", "")
        who = "Kullanıcı" if role == "user" else ("Asistan" if role == "assistant" else role)
        lines.append(f"{who}: {t.get('content', '')}")
    return "\n".join(lines)
