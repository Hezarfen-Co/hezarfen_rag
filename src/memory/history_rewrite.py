"""Faz — history-aware query rewriting (çok-turlu RAG'in EN kritik hafıza parçası).

Sorun: çok-turlu sohbette takip soruları zamir/eksilti içerir ("peki bunun nedeni
ne?", "o enzim ne yapar?"). Ham takip sorusunu retrieval'a vermek YANLIŞ sonuç
getirir (bağlam yok). Çözüm (RES-003 §3, Rewrite-Retrieve-Read): geçmiş + takip
sorusu → DeepSeek ile BAĞIMSIZ (tek-başına-anlaşılır) sorguya çevir → retrieval +
üretim bunu kullanır.

Enjekte edilebilir (test'te stub). Geçmiş boşsa LLM ÇAĞRILMAZ (sorgu aynen döner).
FAIL-SAFE: rewrite hatası → orijinal sorgu (çok-turlu bozulursa tek-turlu gibi çalışır).
Sunucu-tarafı: geçmiş çağıran/auth katmanından gelir (istemci-header'a körü körüne güvenme).
"""
from __future__ import annotations

_SYSTEM = """Sana bir konuşma geçmişi ve bir TAKİP SORUSU verilecek. Takip sorusunu, \
konuşma geçmişine bakmadan TEK BAŞINA anlaşılır, BAĞIMSIZ bir soruya çevir: zamirleri \
("bu", "o", "bunun") ve eksik/ima edilen özneleri geçmişten çözerek açık hale getir. \
Sorunun ANLAMINI değiştirme, yeni bilgi ekleme. Soru zaten bağımsızsa aynen bırak. \
YALNIZCA yeniden yazılmış soruyu döndür — açıklama, tırnak veya başka hiçbir şey yazma."""


def _fmt_history(history, max_turns: int) -> str:
    """Son `max_turns` turu 'Kullanıcı: ... / Asistan: ...' biçiminde diz."""
    turns = history[-max_turns:] if max_turns else history
    lines = []
    for t in turns:
        role = t.get("role", "")
        who = "Kullanıcı" if role == "user" else ("Asistan" if role == "assistant" else role)
        lines.append(f"{who}: {t.get('content', '')}")
    return "\n".join(lines)


class HistoryAwareRewriter:
    """rewrite(history, query) -> bağımsız sorgu. Geçmiş yoksa sorgu aynen döner."""

    def __init__(self, llm=None, *, module: str = "rewrite", cost_recorder=None,
                 max_turns: int = 6, max_tokens: int = 120):
        from ..providers.llm import LLMClient
        self.llm = llm if llm is not None else LLMClient()
        self.module = module
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        from .. import costlog
        self._record = cost_recorder if cost_recorder is not None else costlog.record

    def rewrite(self, history, query: str) -> str:
        if not history or not query or not query.strip():
            return query               # geçmiş yok → LLM çağrılmaz, sorgu aynen
        try:
            user = f"KONUŞMA GEÇMİŞİ:\n{_fmt_history(history, self.max_turns)}\n\nTAKİP SORUSU: {query}"
            r = self.llm.chat(user, system=_SYSTEM, temperature=0.0,
                              max_tokens=self.max_tokens)
            rewritten = (r.text or "").strip().strip('"').strip("'")
            if not rewritten:
                return query           # boş çıktı → orijinali koru
        except Exception:
            return query               # FAIL-SAFE: hata → orijinal sorgu (tek-turlu davran)
        try:
            # #49 (EXP-010/SEC-10) KVKK: burada ogrencinin YAZDIGI metnin ilk 30
            # karakteri `runs.jsonl`a ve oradan `Maliyet.md` tablosuna DUZ METIN
            # olarak geciyordu. Veri minimizasyonu geregi metin artik yazilmaz;
            # teshis icin uzunluk + kisa hash yeter (ayni sorgu tekrar mi geldi
            # sorusu hash ile hâlâ cevaplanabilir, icerik ifsa olmadan).
            import hashlib
            qh = hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:8]
            self._record(module=self.module, model=r.model, usage=r.usage, items=1,
                         note=(f"history-rewrite: q_len={len(query or '')} "
                               f"q_hash={qh} rewritten_len={len(rewritten)}"))
        except Exception:
            pass
        return rewritten
