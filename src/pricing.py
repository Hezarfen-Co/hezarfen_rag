"""DeepSeek fiyatlandırma + maliyet hesabı (tek doğruluk kaynağı: bu dosya).

Fiyatlar 1M token başına USD. Kaynak: DeepSeek resmi fiyat sayfası
(api-docs.deepseek.com/quick_start/pricing), alındığı tarih: 2026-08-28.
Fiyatlar DEĞİŞİR — güncellemek için yalnız `PRICING` tablosunu düzenle,
her yerde otomatik yansır. Değiştirdiğinde `updated` tarihini de güncelle.

Not: DeepSeek "peak" (standart) ve "off-peak" (indirimli ≈ yarı fiyat) uygular.
Bütçeyi TEMKİNLİ tutmak için varsayılan tier = "peak". Off-peak penceresini
resmi sayfadan DOĞRULA (UTC saatleri değişebilir).
"""
from __future__ import annotations
from dataclasses import dataclass

PRICING_UPDATED = "2026-08-28"
PRICING_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing"

# Peak (standart) fiyatlar — USD / 1M token. Off-peak = peak * OFFPEAK_FACTOR.
PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {"in_hit": 0.014, "in_miss": 0.44, "out": 1.32},
    "deepseek-v4-pro":   {"in_hit": 0.044, "in_miss": 1.32, "out": 3.96},
    # görsel varyant flash ile aynı fiyat (doğrula):
    "deepseek-v4-flash-vision-exp": {"in_hit": 0.014, "in_miss": 0.44, "out": 1.32},
}
OFFPEAK_FACTOR = 0.5

# API model id'si ile fiyat-tablosu anahtarı FARKLI olabilir. Buradan eşle.
# DeepSeek API'nin beklediği model id'sini doğrula ve gerekirse düzelt.
MODEL_ALIASES: dict[str, str] = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
}


def resolve(model: str) -> str:
    """API model id'sini fiyat-tablosu anahtarına çevir."""
    return MODEL_ALIASES.get(model, model)


@dataclass
class Usage:
    """Bir LLM çağrısının token kullanımı (DeepSeek/OpenAI-uyumlu usage'dan)."""
    input_cache_hit: int = 0     # prompt_cache_hit_tokens
    input_cache_miss: int = 0    # prompt_cache_miss_tokens
    output: int = 0              # completion_tokens (reasoning/thinking DAHİL)
    reasoning: int = 0           # completion_tokens_details.reasoning_tokens (bilgi amaçlı)

    @property
    def input_total(self) -> int:
        return self.input_cache_hit + self.input_cache_miss

    @property
    def total(self) -> int:
        return self.input_total + self.output

    @classmethod
    def from_api(cls, usage: dict) -> "Usage":
        """DeepSeek/OpenAI-uyumlu `usage` sözlüğünden Usage üret.

        DeepSeek prompt_tokens = cache_hit + cache_miss verir. cache alanları
        yoksa tüm prompt'u cache-miss (en pahalı) say — temkinli.
        """
        hit = usage.get("prompt_cache_hit_tokens")
        miss = usage.get("prompt_cache_miss_tokens")
        if hit is None and miss is None:
            miss = usage.get("prompt_tokens", 0)
            hit = 0
        out = usage.get("completion_tokens", 0)
        det = usage.get("completion_tokens_details") or {}
        reasoning = det.get("reasoning_tokens", 0)
        return cls(input_cache_hit=hit or 0, input_cache_miss=miss or 0,
                   output=out, reasoning=reasoning)


def cost_usd(model: str, usage: Usage, tier: str = "peak") -> float:
    """Bir çağrının USD maliyeti. tier: 'peak' | 'offpeak'."""
    key = resolve(model)
    if key not in PRICING:
        raise KeyError(f"Fiyat tablosunda model yok: {model!r} (çözülen: {key!r}). "
                       f"pricing.PRICING'e ekle.")
    p = PRICING[key]
    factor = OFFPEAK_FACTOR if tier == "offpeak" else 1.0
    usd = (usage.input_cache_hit * p["in_hit"]
           + usage.input_cache_miss * p["in_miss"]
           + usage.output * p["out"]) / 1_000_000.0
    return usd * factor


def price_table_rows() -> list[dict]:
    """Maliyet.md fiyat tablosu için satırlar (peak + offpeak)."""
    rows = []
    for m, p in PRICING.items():
        rows.append({
            "model": m,
            "in_hit": p["in_hit"], "in_miss": p["in_miss"], "out": p["out"],
            "in_hit_off": p["in_hit"] * OFFPEAK_FACTOR,
            "in_miss_off": p["in_miss"] * OFFPEAK_FACTOR,
            "out_off": p["out"] * OFFPEAK_FACTOR,
        })
    return rows
