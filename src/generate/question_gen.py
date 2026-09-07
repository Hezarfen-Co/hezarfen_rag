"""Faz — Benzer / pratik SORU ÜRETİMİ (#5). Özet gibi KAPSAM-tabanlı (retrieval
kullanmaz): verilen kanonik birimlerden öğrenci-tarzı sorular + KAYNAK-SINIRLI kısa
cevaplar üretir. Her soru kaynağa bağlıdır (span_id/sayfa); kaynakta olmayan bilgi
uydurulmaz. Opsiyonel `seed_question` → ona BENZER (aynı kavram/biçim) sorular.

Fail-closed: kapsam boşsa LLM'i HİÇ çağırma (empty_scope). Güvenlik: `seed_question`
verilirse input-guard'dan geçirilir (zararlı seed reddedilir). Maliyet costlog'a yazılır.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .. import costlog
from ..guard.input_guard import check_input
from ..ingest.canonical import CanonicalUnit
from ..pricing import Usage, cost_usd as pricing_cost_usd
from ..providers.deepseek import DeepSeek

_MAX_SOURCE_UNITS = 16          # bir çağrıda kullanılacak azami kaynak birimi (maliyet sınırı)


@dataclass
class GeneratedQuestion:
    soru: str
    cevap: str
    zorluk: str = "orta"        # kolay | orta | zor


@dataclass
class GeneratedQuestionSet:
    items: list = field(default_factory=list)   # [GeneratedQuestion]
    span_ids: list = field(default_factory=list)   # kaynak span'lar (soru seti bunlardan türedi)
    pages: list = field(default_factory=list)
    n_source_units: int = 0
    abstained: bool = False
    reason: str = ""
    usage: Usage | None = None
    cost_usd: float = 0.0
    latency_s: float = 0.0


def _system_prompt(n: int, difficulty: str, seed: str | None) -> str:
    base = (f"Sen bir eğitim içerik uzmanısın. Verilen KAYNAK metinden lise öğrencisi "
            f"için {n} adet DOĞAL, net soru üret ve her biri için YALNIZ bu metne dayanan "
            f"kısa-orta bir cevap yaz. Kaynakta OLMAYAN bilgi ekleme/uydurma. Zorluk: "
            f"{difficulty}. Sorular birbirinden farklı kavramları hedeflesin; kelime "
            f"kopyalama, kavramı sor.")
    if seed:
        base += (f" Üretilen sorular şu örnek soruya BENZER olsun (aynı konu/biçim, farklı "
                 f"ifade): \"{seed}\".")
    base += (' YALNIZCA şu JSON: {"sorular":[{"soru":"...","cevap":"...","zorluk":"kolay|orta|zor"}]}')
    return base


class QuestionGenerator:
    """Kapsam-tabanlı benzer/pratik soru üretimi (retrieval'dan bağımsız)."""

    def __init__(self, deepseek=None, *, module: str = "benzer-soru", cost_recorder=None):
        self.deepseek = deepseek if deepseek is not None else DeepSeek()
        self.module = module
        self._record = cost_recorder if cost_recorder is not None else costlog.record

    def _abstain(self, reason: str) -> GeneratedQuestionSet:
        return GeneratedQuestionSet(items=[], abstained=True, reason=reason)

    def generate(self, units: list[CanonicalUnit], *, n: int = 5, difficulty: str = "orta",
                 seed_question: str | None = None, temperature: float = 0.5,
                 max_tokens: int = 1200) -> GeneratedQuestionSet:
        # FAIL-CLOSED: kapsam yoksa üretme.
        if not units:
            return self._abstain("empty_scope")
        # GÜVENLİK: seed varsa zararlı/injection kontrolü (reddedilirse üretme).
        if seed_question and check_input(seed_question).action == "refuse":
            return self._abstain("guard_seed")

        used = [u for u in units if u.retrievable][:_MAX_SOURCE_UNITS]
        if not used:
            return self._abstain("empty_scope")
        source_text = "\n".join(u.text for u in used)
        system = _system_prompt(n, difficulty, seed_question)
        result = self.deepseek.chat(f"KAYNAK:\n{source_text}\n\nJSON:", system=system,
                                    temperature=temperature, max_tokens=max_tokens,
                                    extra={"response_format": {"type": "json_object"}})
        items: list[GeneratedQuestion] = []
        try:
            data = json.loads(result.text)
            for q in (data.get("sorular") or [])[:n]:
                soru = (q.get("soru") or "").strip()
                cevap = (q.get("cevap") or "").strip()
                zor = (q.get("zorluk") or difficulty).strip().lower()
                if zor not in ("kolay", "orta", "zor"):
                    zor = difficulty
                if soru:                                   # boş soru atlanır (sahte doldurma yok)
                    items.append(GeneratedQuestion(soru=soru, cevap=cevap, zorluk=zor))
        except Exception:
            # parse başarısız → çekimser (uydurma soru döndürme)
            usd0 = pricing_cost_usd(result.model, result.usage)
            self._record(module=self.module, model=result.model, usage=result.usage, items=0,
                         config={"n": n}, note="benzer-soru: JSON parse başarısız")
            return GeneratedQuestionSet(items=[], span_ids=[], pages=[], n_source_units=len(used),
                                        abstained=True, reason="parse_error",
                                        usage=result.usage, cost_usd=usd0, latency_s=result.latency_s)

        usd = pricing_cost_usd(result.model, result.usage)
        self._record(module=self.module, model=result.model, usage=result.usage,
                     items=max(1, len(items)), config={"n": n, "difficulty": difficulty,
                     "seed": bool(seed_question)},
                     note=f"benzer-soru: {len(items)} soru / {len(used)} kaynak birimi")
        span_ids = sorted({u.span_id for u in used})
        pages = sorted({u.page for u in used})
        return GeneratedQuestionSet(items=items, span_ids=span_ids, pages=pages,
                                    n_source_units=len(used), abstained=not items,
                                    reason="" if items else "no_questions",
                                    usage=result.usage, cost_usd=usd, latency_s=result.latency_s)
