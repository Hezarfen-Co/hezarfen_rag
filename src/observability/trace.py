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
import os
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


# M4-11 (#85, EXP-010/OPS-12) — TRACE URETIMDE HIC URETILMIYORDU.
#
# grep ile dogrulandi: `RequestTrace` yalniz `trace.py` ve
# `observability/__init__.py`'de geciyordu. `RagService.chat` `trace=`
# gecirmiyor -> `Generator.answer(trace=None)` -> butun `_tr()` cagrilari
# NO-OP. Sink yok, `request_id` yanita donmuyor.
#
# SONUC: YENIDEN-OYNATILABILIRLIK YOK. "Neden bu cevabi verdi?" sorusu geriye
# donuk cevaplanamiyor; kalite regresyonu ve sikayet incelemesi imkansiz.
#
# HASSAS ICERIK: #49 (KVKK) ile uyumlu olmak zorunda -- ogrencinin sorgu
# METNI ize YAZILMAZ; yalniz uzunluk + kisa hash tutulur. Sorgu metnini
# yazmak, silinmesi gereken bir kisisel veriyi ikinci bir yere kopyalamak
# demektir.

TRACE_PATH = os.environ.get("HEZARFEN_TRACE_PATH") or ""
TRACE_SAMPLE = float(os.environ.get("HEZARFEN_TRACE_SAMPLE", "1.0"))


def redact(text: str | None) -> dict:
    """Sorgu metnini ize yazmadan tanınabilir kılar (#49 ile uyumlu)."""
    import hashlib
    ham = text or ""
    return {"len": len(ham),
            "hash": hashlib.sha256(ham.encode("utf-8")).hexdigest()[:12]}


def write_trace(trace, path: str | None = None, *, sample: float | None = None,
                rng=None) -> bool:
    """İzi JSONL sink'e yazar. Döner: yazıldı mı.

    ÖRNEKLEME: yoğun trafikte her isteği yazmak diski doldurur. `sample=0.1`
    izlerin %10'unu tutar. **Çekimser ve hatalı istekler HER ZAMAN yazılır** —
    incelenmesi gereken tam olarak onlardır; örnekleme onları atarsa
    izlenebilirlik en çok ihtiyaç duyulan yerde kaybolur.

    Telemetri hatası isteği ASLA düşürmez (aynı ilke: costlog, audit).
    """
    import json as _json
    import random as _random
    hedef = path if path is not None else TRACE_PATH
    if not hedef:
        return False
    d = trace.to_dict() if hasattr(trace, "to_dict") else dict(trace)
    oran = TRACE_SAMPLE if sample is None else sample
    # DIKKAT: `TraceEvent.to_dict()` meta'yi DUZLESTIRIR (ayri bir "meta"
    # anahtari YOKTUR). Ilk surumde `e.get("meta", {})` yaziyordum ve bu yuzden
    # ONEMLI izler hicbir zaman taninmiyor, ornekleme onlari da atiyordu --
    # yani izlenebilirlik tam ihtiyac duyulan yerde kayboluyordu.
    onemli = any(e.get("abstained") or e.get("name") == "error"
                 for e in d.get("events", []))
    if not onemli and oran < 1.0:
        r = (rng or _random.random)()
        if r >= oran:
            return False
    try:
        os.makedirs(os.path.dirname(hedef) or ".", exist_ok=True)
        with open(hedef, "a", encoding="utf-8") as fh:
            fh.write(_json.dumps(d, ensure_ascii=False) + "\n")
        return True
    except Exception:                            # noqa: BLE001
        return False


def read_traces(path: str | None = None) -> list[dict]:
    import json as _json
    hedef = path if path is not None else TRACE_PATH
    if not hedef or not os.path.isfile(hedef):
        return []
    out = []
    with open(hedef, encoding="utf-8") as fh:
        for satir in fh:
            satir = satir.strip()
            if satir:
                try:
                    out.append(_json.loads(satir))
                except Exception:                # noqa: BLE001
                    continue
    return out
