"""DeepSeek LLM sağlayıcı (OpenAI-uyumlu /chat/completions).

Amaç: metin üret + TOKEN KULLANIMINI döndür ki maliyet hesaplanabilsin.
API anahtarı env `DEEPSEEK_API_KEY`'den okunur; anahtar OLMADAN da import edilir
(offline test için). Gerçek çağrı yalnız `.chat()` çağrılınca yapılır.

Dönen: ChatResult(text, usage: pricing.Usage, model, raw). Maliyet için:
    from src.pricing import cost_usd
    r = DeepSeek().chat("Özetle: ...")
    usd = cost_usd(r.model, r.usage)
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field

from ..pricing import Usage

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"   # API model id — pricing.MODEL_ALIASES ile fiyata eşlenir


@dataclass
class ChatResult:
    text: str
    usage: Usage
    model: str
    latency_s: float = 0.0
    raw: dict = field(default_factory=dict)


class DeepSeek:
    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE,
                 api_key: str | None = None, timeout: float = 120.0):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Anahtar burada ZORUNLU değil — yalnız chat() sırasında gerekir.
        self._api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")

    def chat(self, prompt: str, system: str | None = None, *,
             temperature: float = 0.2, max_tokens: int | None = None,
             extra: dict | None = None) -> ChatResult:
        if not self._api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY yok. `setx DEEPSEEK_API_KEY <key>` ya da "
                "DeepSeek(api_key=...) ile ver.")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature, "stream": False}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self._api_key}"},
            method="POST")
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latency = time.time() - t0

        # content None olabilir (finish_reason=length / içerik-filtresi / yalnız-reasoning
        # turu) → "" (aksi halde çağıran taraf _parse_citation_ns(None) vb. ile çöker).
        # choices boşsa da güvenli boş dön (audit EXP-007).
        choices = data.get("choices") or [{}]
        text = (choices[0].get("message", {}) or {}).get("content") or ""
        usage = Usage.from_api(data.get("usage", {}))
        return ChatResult(text=text, usage=usage, model=self.model,
                          latency_s=latency, raw=data)
