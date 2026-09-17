"""ResponseCache — `canonical(query+role+model+top_n+candidate_n+ders+...) ->
GroundedAnswer` (bkz. docs/OPTIMIZATION.md §C, RES-002 §4).

RagArt dersi (RES-002 §4): "ResponseCache DeepSeek çağrısını SIFIRLAR = en
büyük maliyet kazancı." Hit olursa `src/generate/generator.py` LLM'i (ve
retrieval'i) HİÇ ÇALIŞTIRMAZ -> `cost_usd == 0.0` GERÇEKTEN sıfırdır (simüle
değil) çünkü DeepSeek'e ağ çağrısı yapılmaz.

**Anahtar tasarımı (RagArt'ın hatasından kaçınma):** cevabı DEĞİŞTİREBİLECEK
HER parametre anahtara girer — yalnız `query` değil; `role` (rol-türevli
erişim farklıysa aynı soru farklı cevap/erişim alabilir), `model` (farklı
model = farklı cevap kalitesi/maliyeti), `top_n`/`candidate_n` (retrieval
genişliği cevabı değiştirir), `ders` (aynı soru farklı derste farklı kaynak
havuzuna düşer). `extra` ile gerekirse "seçili kaynak" gibi ek ayırt edici
alanlar da eklenir. Bu alanlardan biri EKSİK kalırsa yanlış cache HIT riski
oluşur (RagArt'ın tam da düştüğü tuzak) — yeni bir parametre cevabı
etkileyebiliyorsa `canonical_key`'e eklenmeden entegre EDİLMEMELİ.
"""
from __future__ import annotations

import hashlib
import json

from .base import BaseCache, SQLiteCache

DEFAULT_TTL_SECONDS = 3600.0  # 1 saat — config edilebilir (ResponseCache(ttl=...))


def canonical_key(*, query: str, role: str = "", model: str = "", top_n: int = 0,
                  candidate_n: int = 0, ders: str = "", corpus_version: str = "",
                  school: str = "", extra: dict | None = None) -> str:
    """Cevabı etkileyebilecek parametreleri deterministik JSON'a çevirip sha256'la.
    `sort_keys=True` -> alan sırası anahtarı etkilemez; yalnız DEĞERLER etkiler.
    `corpus_version` (AUDIT EXP-007 #30/M2): kaynak yeniden-indekslenince (doc_id/
    source_version değişince) anahtar da değişsin → re-ingest sonrası TTL boyunca
    ESKİ cevap/atıf dönmesin. Boş "" ise davranış öncekiyle aynı.

    `school` (kiracılık, 2026-09-17): okulun içeriği başka bir okula ASLA
    dönmemeli — cevap + atıflar okula bağlı olduğu için anahtar da okula bağlı
    olmak ZORUNDA. Bu alan olmadan iki okulun aynı sorusu TEK anahtara düşer ve
    `cache_hit` cevabı okullar arası taşır (tek süreç = çok okul)."""
    payload = {
        "query": query, "role": role, "model": model,
        "top_n": top_n, "candidate_n": candidate_n, "ders": ders,
        "corpus_version": corpus_version, "school": school,
        "extra": extra or {},
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResponseCache:
    """key=canonical_key(...) -> GroundedAnswer (pickle ile serialize, bkz.
    SQLiteCache). TTL varsayılan 1 saat (`DEFAULT_TTL_SECONDS`) — RagArt'ın
    aksine burada `costlog`/`CacheStats` ile hit/miss GERÇEKTEN ölçülür."""

    def __init__(self, backend: BaseCache | None = None, *, ttl: float = DEFAULT_TTL_SECONDS):
        self.backend = backend if backend is not None else SQLiteCache()
        self.ttl = ttl

    def get(self, *, query: str, role: str = "", model: str = "", top_n: int = 0,
           candidate_n: int = 0, ders: str = "", corpus_version: str = "",
           school: str = "", extra: dict | None = None):
        key = canonical_key(query=query, role=role, model=model, top_n=top_n,
                            candidate_n=candidate_n, ders=ders,
                            corpus_version=corpus_version, school=school,
                            extra=extra)
        return self.backend.get(key)

    def set(self, answer, *, query: str, role: str = "", model: str = "", top_n: int = 0,
           candidate_n: int = 0, ders: str = "", corpus_version: str = "",
           school: str = "", extra: dict | None = None) -> None:
        key = canonical_key(query=query, role=role, model=model, top_n=top_n,
                            candidate_n=candidate_n, ders=ders,
                            corpus_version=corpus_version, school=school,
                            extra=extra)
        self.backend.set(key, answer, ttl=self.ttl)

    @property
    def stats(self):
        return self.backend.stats
