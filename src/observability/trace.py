"""Faz — İstek izleme (#18, observability). Bir RAG isteğinin KARAR İZİ + adım
süreleri: guard verdikti, cache hit/miss, retrieval hit sayısı, rerank top skoru +
abstain eşiği, nihai karar (cevap/çekimser + reason), maliyet.

Neden hafif + bağımlılıksız: üretimde OpenTelemetry/collector eklenebilir (backlog),
ama önce KENDİ karar-izimizi görebilmeliyiz — "neden çekimser kaldı? ne getirildi?
hangi adım yavaş?" sorularını yanıtlar. `Generator.answer(trace=...)` opsiyonel;
None ise HİÇBİR ek maliyet yok (mevcut davranış birebir korunur).
"""
from __future__ import annotations

import contextlib
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class TraceEvent:
    name: str
    t_ms: float                 # istek başından beri geçen ms
    meta: dict = field(default_factory=dict)


class RequestTrace:
    """Tek bir isteğin olay/karar izi. Thread-güvenli değildir (istek başına bir tane)."""

    def __init__(self, request_id: str | None = None):
        self.request_id = request_id or uuid.uuid4().hex[:12]
        self._t0 = time.perf_counter()
        self.events: list[TraceEvent] = []

    def _now_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0

    def event(self, name: str, **meta) -> None:
        self.events.append(TraceEvent(name=name, t_ms=round(self._now_ms(), 2), meta=meta))

    @contextlib.contextmanager
    def span(self, name: str, **meta):
        """Bir adımı zamanla; bitişte `<name>` olayını `dur_ms` ile kaydeder."""
        start = time.perf_counter()
        try:
            yield
        finally:
            dur = (time.perf_counter() - start) * 1000.0
            self.event(name, dur_ms=round(dur, 2), **meta)

    @property
    def total_ms(self) -> float:
        return round(self._now_ms(), 2)

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "total_ms": self.total_ms,
            "events": [{"name": e.name, "t_ms": e.t_ms, **e.meta} for e in self.events],
        }

    def summary(self) -> str:
        """Tek satır özet (log için): karar + toplam süre + varsa reason."""
        decision = next((e for e in reversed(self.events) if e.name == "decision"), None)
        d = decision.meta if decision else {}
        return (f"[trace {self.request_id}] {self.total_ms:.0f}ms "
                f"decision={d.get('abstained') and 'abstain' or 'answer'} "
                f"reason={d.get('reason','')!r} events={len(self.events)}")
