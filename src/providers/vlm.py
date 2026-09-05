"""VLM (görme-dil) sağlayıcı — görsel içerik captioning (Faz 5, #23).

Sağlayıcı-BAĞIMSIZ: OpenAI-uyumlu `/chat/completions` (mesajda `image_url` data-URI
bloğu) konuşan HERHANGİ bir VLM API'sine bağlanır — base_url/model/key env'den:
  VLM_BASE_URL (ör. https://openrouter.ai/api/v1, .../gemini OpenAI-compat, https://api.openai.com/v1)
  VLM_MODEL    (ör. google/gemini-2.0-flash, gpt-4o-mini, qwen/qwen2-vl-72b-instruct)
  VLM_API_KEY

Karar (Kadir 2026-09-06): yerel VLM DEĞİL, API. Sağlayıcı seçimi env ile; kod aynı.

Zarif degradasyon (OCR deseniyle aynı): key/base/model yoksa `available()` False,
`caption()` "" döner (çağıran görsel-birim üretmeden devam eder). Gerçek HTTP çağrısı
yalnız `caption()` çağrılınca yapılır — anahtarsız import + test edilebilir.

Dönen maliyet: `caption_with_usage()` (text, Usage) verir → pricing.cost_usd ile $ hesaplanır.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field

from ..pricing import Usage

# Türkçe, öğretim-odaklı captioning yönergesi (görsel içerikten METİN çıkarımı).
DEFAULT_CAPTION_PROMPT = (
    "Bu bir ders kitabı sayfasındaki görsel içeriktir (şema, diyagram, grafik, "
    "resim, tablo veya sanat eseri olabilir). Görselin ÖĞRETİCİ içeriğini Türkçe, "
    "nesnel ve ayrıntılı biçimde betimle: ne gösteriyor, hangi kavramı/olayı "
    "anlatıyor, üzerindeki etiket/başlık/sayılar neler. Görselde OLMAYAN bilgi "
    "UYDURMA. Yalnız betimlemeyi yaz, ön söz ekleme."
)


@dataclass
class CaptionResult:
    text: str
    usage: Usage
    model: str
    latency_s: float = 0.0
    raw: dict = field(default_factory=dict)


class VLMCaptioner:
    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key: str | None = None, timeout: float = 120.0):
        self.model = model or os.environ.get("VLM_MODEL")
        base = base_url or os.environ.get("VLM_BASE_URL")
        self.base_url = base.rstrip("/") if base else None
        self.timeout = timeout
        self._api_key = api_key or os.environ.get("VLM_API_KEY")

    def available(self) -> bool:
        """Gerçek çağrı yapılabilir mi (key + base + model tanımlı)."""
        return bool(self._api_key and self.base_url and self.model)

    def caption_with_usage(self, image_png: bytes, *, prompt: str = DEFAULT_CAPTION_PROMPT,
                           max_tokens: int = 512, temperature: float = 0.2) -> CaptionResult:
        """PNG baytlarını VLM'e gönderip Türkçe betim + token kullanımı döndürür.
        Kullanılamıyorsa/çağrı patlarsa boş CaptionResult (zarif degradasyon)."""
        if not self.available():
            return CaptionResult(text="", usage=Usage(), model=self.model or "", raw={})
        try:
            b64 = base64.b64encode(image_png).decode("ascii")
            data_uri = f"data:image/png;base64,{b64}"
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ]}],
                "max_tokens": max_tokens, "temperature": temperature, "stream": False,
            }
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
            text = (data["choices"][0]["message"]["content"] or "").strip()
            usage = Usage.from_api(data.get("usage", {}))
            return CaptionResult(text=text, usage=usage, model=self.model,
                                 latency_s=latency, raw=data)
        except Exception:
            return CaptionResult(text="", usage=Usage(), model=self.model or "", raw={})

    def caption(self, image_png: bytes, **kw) -> str:
        """Yalnız betim metni (maliyet gerekmezse)."""
        return self.caption_with_usage(image_png, **kw).text
