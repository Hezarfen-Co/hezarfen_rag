"""OpenAI-uyumlu /chat/completions LLM sağlayıcı — SAĞLAYICI-BAĞIMSIZ.

Amaç: metin üret + TOKEN KULLANIMINI döndür ki maliyet hesaplanabilsin.
API anahtarı env `LLM_API_KEY`'den okunur; anahtar OLMADAN da import edilir
(offline test için). Gerçek çağrı yalnız `.chat()` çağrılınca yapılır.

Dönen: ChatResult(text, usage: pricing.Usage, model, raw). Maliyet için:
    from src.pricing import cost_usd
    r = LLMClient().chat("Özetle: ...")
    usd = cost_usd(r.model, r.usage)

## Sağlayıcı değiştirme (KOD DEĞİŞMEZ) — EXP-009
`mimari.md §0.1`: üretici LLM "kanıtlanmış varsayılan" DEĞİL, **ADAY**.
Aday karşılaştırması yapabilmek için uç nokta/model/anahtar **env'den** gelir:

    LLM_BASE_URL   OpenAI-uyumlu taban (ör. https://integrate.api.nvidia.com/v1)
    LLM_MODEL      model id (ör. moonshotai/kimi-k3)
    LLM_API_KEY    o sağlayıcının anahtarı
    LLM_EXTRA_JSON her istek gövdesine eklenecek JSON (sağlayıcıya özgü parametre)

## TEMİZ KESİM — eski sağlayıcı adları YOK (2026-09-17)

Filo ad sözleşmesi (kullanıcı, 2026-09-17): bir kavramın TEK adı olur. LLM
anahtarı `LLM_API_KEY`'dir; `DEEPSEEK_API_KEY` / `NVIDIA_API_KEY` gibi
sağlayıcıya bağlı adlar KALDIRILDI. "Eski ad da çalışsın" diye bir geri düşüş
bırakmak "hangi ad kazandı" sorusunu kodun içine taşırdı — onun yerine eski bir
ad ORTAMDA GÖRÜLÜRSE yapılandırma AÇIKÇA REDDEDİLİR (`reject_retired_env`):
sessizce yeni ada düşen bir kurulum, adı değişmemiş bir operatörü fark
ettirmez (aynı desen: hezarfen_zeka `ESKI_LLM_ADLARI`).

`LLM_EXTRA_JSON` NEDEN var (ampirik, 2026-09-10): reasoning modelleri
`max_tokens` bütçesinin tamamını düşünmeye harcayıp **boş içerik** döndürüyor
(EXP-006'daki `deepseek-v4-flash-vision-exp` hatasının aynısı). Çözüm sağlayıcıya
göre değişiyor: DeepSeek/Kimi/Muse → `{"reasoning_effort": "none"}`,
NVIDIA Nemotron → `{"chat_template_kwargs": {"thinking": false}}`. Bunu koda
gömmek yerine env'e almak, sağlayıcı-bağımsızlığı bozmadan çözer.
Açık `extra=` argümanı env'in ÜSTÜNE yazar (çağrı-başına kontrol korunur).
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field

from ..pricing import Usage
from .resilience import (CircuitBreaker, ProviderBodyError, call_with_retry,
                         provider_error_from_body,
                         is_retryable as _is_retryable)

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"   # API model id — pricing.MODEL_ALIASES ile fiyata eşlenir

#: Anahtarın TEK adı — sağlayıcı adı taşıyan bir yedek YOKTUR.
LLM_API_KEY_ENV = "LLM_API_KEY"

#: KALDIRILAN adlar. Dolu bulunurlarsa yapılandırma reddedilir: yarım kalan bir
#: adı sessizce yok saymak, operatörün kendi ayar dosyasının artık okunmadığını
#: fark etmemesi demek olurdu.
RETIRED_ENV_NAMES: tuple[str, ...] = ("DEEPSEEK_API_KEY", "NVIDIA_API_KEY")


class LLMConfigError(RuntimeError):
    """Yapılandırma hatası (kaldırılmış ad / eksik zorunlu değer)."""


def _env(name: str) -> str | None:
    """Env değeri; BOŞ string = ayarlanmamış (`.env` boş satır bırakabiliyor)."""
    val = os.environ.get(name)
    return val.strip() if val and val.strip() else None


def reject_retired_env() -> None:
    """Kaldırılmış LLM adları ORTAMDA varsa reddet (değer yazdırmadan).

    Çağrı noktaları: `LLMClient.__init__` (her kurulum yolu) + servis açılışı.
    """
    eski = [ad for ad in RETIRED_ENV_NAMES if _env(ad)]
    if eski:
        raise LLMConfigError(
            "şu adlar artık DESTEKLENMİYOR: " + ", ".join(eski)
            + ". Yeni adlar: LLM_API_KEY, LLM_BASE_URL, LLM_MODEL. "
            "Eski adı `.env`den/ortamdan silin — yok sayılmaz, açıkça reddedilir.")


def _env_extra() -> dict:
    """`LLM_EXTRA_JSON` → dict. Bozuk JSON sessizce yutulmaz: uyarı + {}."""
    raw = _env("LLM_EXTRA_JSON")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        import warnings
        warnings.warn("LLM_EXTRA_JSON geçerli JSON değil → yok sayıldı.", stacklevel=2)
        return {}
    if not isinstance(data, dict):
        import warnings
        warnings.warn("LLM_EXTRA_JSON bir JSON nesnesi olmalı → yok sayıldı.", stacklevel=2)
        return {}
    return data


@dataclass
class ChatResult:
    text: str
    usage: Usage
    model: str
    latency_s: float = 0.0
    raw: dict = field(default_factory=dict)


DEFAULT_TIMEOUT = float(os.environ.get("LLM_TIMEOUT_S", "30"))


class LLMClient:
    """OpenAI-uyumlu sohbet istemcisi.

    Öncelik: açık argüman > env (`LLM_*`) > DeepSeek varsayılanı. Böylece mevcut
    çağıranların (Generator/Summarizer/guard/rewrite/judge) hiçbiri değişmeden
    tüm sistem başka bir sağlayıcıya alınabilir (aday karşılaştırması, EXP-009).
    """

    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key: str | None = None, timeout: float | None = None,
                 extra: dict | None = None, breaker=None,
                 max_attempts: int | None = None):
        reject_retired_env()          # kaldırılmış ad: burada DURUR, sessizce yok saymaz
        self.model = model or _env("LLM_MODEL") or DEFAULT_MODEL
        base = base_url or _env("LLM_BASE_URL") or DEFAULT_BASE
        self.base_url = base.rstrip("/")
        # #78 (EXP-010/OPS-06): varsayilan 120 s IDI ve SAVUNULAMAZDI.
        # Olculen LLM p50'leri 1,94-10,44 s; 120 s'lik tavan ogrenciyi iki
        # dakika bekletip sonunda hata gostermek demek. Ayrica saglayici
        # bozuksa her istek 120 s bir thread tutar, anyio havuzu (40) dolar ve
        # `/health` bile yanit veremez.
        self.timeout = DEFAULT_TIMEOUT if timeout is None else timeout
        self.breaker = breaker if breaker is not None else CircuitBreaker()
        self.max_attempts = max_attempts
        # Her isteğe eklenecek sağlayıcıya-özgü gövde parametreleri.
        self.extra = dict(extra) if extra is not None else _env_extra()
        # Anahtar burada ZORUNLU değil — yalnız chat() sırasında gerekir.
        self._api_key = api_key or _env(LLM_API_KEY_ENV)

    def chat(self, prompt: str, system: str | None = None, *,
             temperature: float = 0.2, max_tokens: int | None = None,
             extra: dict | None = None) -> ChatResult:
        if not self._api_key:
            raise LLMConfigError(
                f"API anahtarı yok. `.env`'e {LLM_API_KEY_ENV} yaz ya da "
                "LLMClient(api_key=...) ile ver.")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature, "stream": False}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        # Sağlayıcı-geneli parametreler (env/ctor) ÖNCE, çağrı-başına `extra`
        # SONRA → tek bir çağrı (ör. guard'ın response_format'ı) env'i geçersiz
        # kılabilsin.
        if self.extra:
            payload.update(self.extra)
        if extra:
            payload.update(extra)

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self._api_key}"},
            method="POST")
        def _gonder():
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            # GEÇİT 2xx GÖVDESİNDE HATA DÖNDÜREBİLİR (Kilo/OpenRouter, yük
            # altında HTTP 200 + `{"error":{"code":503,...}}`). Durum koduna
            # bakmak bunu başarı sayar; `choices` okunamayınca geriye sessiz bir
            # boş metin kalırdı. Sınıflandırma `_is_retryable`'da: geçici kod
            # yeniden denenir, kalıcı kod sağlayıcının kendi mesajıyla biter.
            hata = provider_error_from_body(data)
            if hata is not None:
                raise ProviderBodyError(hata[0], status=hata[1])
            return data

        t0 = time.time()
        # #78: jitter'lı üstel yeniden deneme + devre kesici. Jitter ŞART —
        # EXP-009'da yaşanan %92 HTTP 429, eş zamanlı tekrar denemelerden
        # oluşmuştu (4 worker aynı modele aynı anda vuruyordu).
        data = call_with_retry(_gonder, is_retryable=_is_retryable,
                               max_attempts=self.max_attempts,
                               breaker=self.breaker)
        latency = time.time() - t0

        # content None olabilir (finish_reason=length / içerik-filtresi / yalnız-reasoning
        # turu) → "" (aksi halde çağıran taraf _parse_citation_ns(None) vb. ile çöker).
        # choices boşsa da güvenli boş dön (audit EXP-007).
        choices = data.get("choices") or [{}]
        text = (choices[0].get("message", {}) or {}).get("content") or ""
        usage = Usage.from_api(data.get("usage", {}))
        return ChatResult(text=text, usage=usage, model=self.model,
                          latency_s=latency, raw=data)
