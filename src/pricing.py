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
    # NVIDIA NIM "Free Endpoint" — aday karşılaştırması (EXP-009) buradan koşar.
    # ⚠️ 0.0 = ÜCRETSİZ UÇ; kalıcı bir fiyat DEĞİL. Ücretsiz uçta kota/gecikme
    # riski var (ölçüldü: model başına eşzamanlılık ~1). Üretime alınırsa
    # sağlayıcının gerçek fiyatı buraya YAZILMALI, yoksa maliyet eksik sayılır.
    "nim-free": {"in_hit": 0.0, "in_miss": 0.0, "out": 0.0},
}
OFFPEAK_FACTOR = 0.5

# API model id'si ile fiyat-tablosu anahtarı FARKLI olabilir. Buradan eşle.
# DeepSeek canlı /models kataloğu (doğrulandı 2026-09-10): ['deepseek-flash',
# 'deepseek-v4-pro']; 'deepseek-chat'/'deepseek-reasoner' hâlâ kabul ediliyor.
MODEL_ALIASES: dict[str, str] = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-flash": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
    # NVIDIA NIM ücretsiz uç noktalar (LLM_BASE_URL=integrate.api.nvidia.com/v1)
    "deepseek-ai/deepseek-v4-flash-0731": "nim-free",
    "deepseek-ai/deepseek-v4-pro-0813": "nim-free",
    "moonshotai/kimi-k3": "nim-free",
    "meta/muse-glimmer-30b": "nim-free",
    "nvidia/nemotron-3.5-lightning-30b-a3b": "nim-free",
    "nvidia/nemotron-3-super-120b-a12b": "nim-free",
    "nvidia/nemotron-3-ultra-550b-a55b": "nim-free",
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
    """Bir çağrının USD maliyeti. tier: 'peak' | 'offpeak'.

    Bilinmeyen model → KeyError DEĞİL: uyarı + 0.0 döner. Neden (audit EXP-007):
    DeepSeek model kimlikleri değişebiliyor (v4/vision churn); fiyat tablosunda
    olmayan bir model YÜZÜNDEN kullanıcının cevabını/özetini ya da costlog kaydını
    ÇÖKERTMEK, maliyeti eksik saymaktan daha kötü. Eksik fiyatı görmek için uyarı
    loglanır (pricing.PRICING'e eklenmeli)."""
    key = resolve(model)
    if key not in PRICING:
        import warnings
        warnings.warn(f"pricing: bilinmeyen model {model!r} (çözülen {key!r}) → "
                      f"maliyet 0.0 sayıldı; pricing.PRICING'e ekle.", stacklevel=2)
        return 0.0
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
