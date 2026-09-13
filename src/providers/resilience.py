"""LLM çağrılarında dayanıklılık: yeniden deneme + devre kesici (#78).

ÖLÇÜLEN DURUM (EXP-010/OPS-06):
* `providers/deepseek.py` tek `urlopen` ile çağırıyordu — **retry/backoff YOK**,
  `timeout=120.0`.
* `RagService.chat` LLM hatasını yakalamıyordu; stub 429 ile ölçüldü → yanıt
  **HTTP 500**, gövde `"Internal Server Error"` (reason yok, request_id yok).
* Gerçek hayat kanıtı (EXP-009): DeepSeek/NVIDIA uçlarında **%92 HTTP 429** ve
  300 s timeout yaşandı.

İKİ TASARIM KARARI:

1. **`timeout=120` savunulamaz.** Ölçülen LLM p50'leri 1,94–10,44 s. 120 s'lik
   tavan, öğrenciyi iki dakika bekletip sonunda hata göstermek demek. Varsayılan
   **30 s**'ye çekildi; toplam istek bütçesi ayrıca sınırlı.
2. **Devre kesici şart.** Sağlayıcı 10 dakika bozuksa, kesici olmadan her istek
   tam `timeout` kadar bir thread tutar; anyio havuzu (40) dolar ve
   **`/health` bile yanıt veremez**. Kesici açıkken çağrı **anında** düşer.

Ayrıca `llm_classifier` hatada artık `_degraded_scan`'e düşüyor (#49); yani
sağlayıcı arızası ikinci güvenlik katmanını sessizce kapatmıyor.
"""
from __future__ import annotations

import os
import random
import threading
import time

# Yeniden denenebilir HTTP durumları: yalnız geçici olanlar.
# 400/401/403/404/422 DENENMEZ — istek yanlış, tekrarlamak yalnız kota yakar.
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

MAX_ATTEMPTS = int(os.environ.get("LLM_MAX_ATTEMPTS", "3"))
BASE_DELAY_S = float(os.environ.get("LLM_RETRY_BASE_S", "0.5"))
MAX_DELAY_S = float(os.environ.get("LLM_RETRY_MAX_S", "8.0"))
REQUEST_BUDGET_S = float(os.environ.get("LLM_REQUEST_BUDGET_S", "45"))
BREAKER_THRESHOLD = int(os.environ.get("LLM_BREAKER_THRESHOLD", "5"))
BREAKER_COOLDOWN_S = float(os.environ.get("LLM_BREAKER_COOLDOWN_S", "30"))


class LlmUnavailable(RuntimeError):
    """Sağlayıcıya ulaşılamadı / geçici hata sürüyor.

    TİPLİ olması şart: çağıran taraf bunu `abstained=True,
    reason="llm_unavailable"` sözleşmesine çevirir. Eskiden çıplak bir istisna
    yukarı çıkıyor ve kullanıcıya `"Internal Server Error"` olarak dönüyordu.
    """

    def __init__(self, message: str, *, status: int | None = None,
                 attempts: int = 0, elapsed_s: float = 0.0):
        super().__init__(message)
        self.status = status
        self.attempts = attempts
        self.elapsed_s = elapsed_s


class CircuitBreaker:
    """Ardışık hata eşiği aşılınca çağrıları ANINDA düşüren kesici.

    Durumlar: kapalı (normal) → açık (düşür) → yarı-açık (tek deneme).
    Yarı-açıkta **tek** çağrıya izin verilir; başarılıysa kapanır, değilse
    yeniden açılır ve bekleme süresi baştan başlar.

    DÜRÜST SINIR: süreç-içidir. Çok-worker dağıtımda her worker kendi
    kesicisini tutar; paylaşımlı durum için harici bir sayaç gerekir (#86).
    """

    def __init__(self, *, threshold: int | None = None,
                 cooldown_s: float | None = None, clock=time.monotonic):
        self.threshold = BREAKER_THRESHOLD if threshold is None else threshold
        self.cooldown_s = BREAKER_COOLDOWN_S if cooldown_s is None else cooldown_s
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_inflight = False

    @property
    def state(self) -> str:
        with self._lock:
            return self._state_unlocked()

    def _state_unlocked(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self.cooldown_s:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        """Çağrıya izin var mı. Yarı-açıkta yalnız TEK deneme geçer."""
        with self._lock:
            state = self._state_unlocked()
            if state == "closed":
                return True
            if state == "open":
                return False
            if self._half_open_inflight:
                return False           # deneme zaten uçuşta
            self._half_open_inflight = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open_inflight = False

    def record_failure(self) -> None:
        with self._lock:
            half_open = (self._opened_at is not None
                         and self._clock() - self._opened_at >= self.cooldown_s)
            self._half_open_inflight = False
            # TESTLE BULUNDU: yarı-açıkta başarısız olan deneme kesiciyi HEMEN
            # yeniden açmalı. İlk sürümde yalnız sayaç artıyordu; sayaç eşiğin
            # altındaysa `_opened_at` eski değerinde kalıyor ve durum
            # "yarı-açık" görünmeye devam ediyordu — yani arızalı sağlayıcıya
            # her istekte yeniden bir deneme gidiyordu ve kesici fiilen
            # çalışmıyordu.
            if half_open:
                self._opened_at = self._clock()
                self._failures = 0
                return
            self._failures += 1
            if self._failures >= self.threshold:
                self._opened_at = self._clock()
                self._failures = 0     # bekleme sonrası taze sayım

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self._state_unlocked(),
                    "consecutive_failures": self._failures,
                    "threshold": self.threshold, "cooldown_s": self.cooldown_s}


def backoff_delay(attempt: int, *, base: float | None = None,
                  cap: float | None = None, rng=random.random) -> float:
    """Jitter'lı üstel bekleme. `attempt` 1'den başlar.

    JITTER ŞART: sağlayıcı 429 verdiğinde tüm istemciler aynı anda tekrar
    denerse yük dalgası aynen tekrarlanır (EXP-009'da %92 429 tam olarak böyle
    oluştu — 4 worker aynı modele aynı anda vuruyordu).
    """
    b = BASE_DELAY_S if base is None else base
    c = MAX_DELAY_S if cap is None else cap
    tavan = min(c, b * (2 ** max(0, attempt - 1)))
    return tavan * (0.5 + 0.5 * rng())        # [%50, %100] aralığında


def call_with_retry(fn, *, is_retryable, max_attempts: int | None = None,
                    budget_s: float | None = None, breaker: CircuitBreaker | None = None,
                    sleep=time.sleep, clock=time.monotonic, rng=random.random,
                    on_retry=None):
    """`fn()`'i dayanıklılık kurallarıyla çağırır.

    `is_retryable(exc) -> (bool, status|None)` — hangi hatanın tekrar
    denenebilir olduğuna ÇAĞIRAN karar verir (taşıma ayrıntısı buraya sızmasın).

    Bütçe (`budget_s`) toplam süreyi sınırlar: bir sonraki bekleme bütçeyi
    aşacaksa **beklemeden** vazgeçilir. Aksi hâlde "3 deneme × 30 s + bekleme"
    kullanıcıyı dakikalarca bekletirdi.
    """
    n = MAX_ATTEMPTS if max_attempts is None else max_attempts
    butce = REQUEST_BUDGET_S if budget_s is None else budget_s
    t0 = clock()

    if breaker is not None and not breaker.allow():
        raise LlmUnavailable("devre kesici açık — sağlayıcı arızalı sayılıyor",
                             attempts=0, elapsed_s=0.0)

    son_hata = None
    son_status = None
    for deneme in range(1, n + 1):
        try:
            sonuc = fn()
        except Exception as e:                       # noqa: BLE001
            tekrar, status = is_retryable(e)
            son_hata, son_status = e, status
            if breaker is not None:
                breaker.record_failure()
            if not tekrar or deneme >= n:
                break
            gecen = clock() - t0
            bekleme = backoff_delay(deneme, rng=rng)
            if gecen + bekleme >= butce:
                break                                # bütçe: beklemeden vazgeç
            if on_retry is not None:
                on_retry(deneme, status, bekleme)
            sleep(bekleme)
            continue
        if breaker is not None:
            breaker.record_success()
        return sonuc

    raise LlmUnavailable(f"sağlayıcı yanıt vermedi: {son_hata}",
                         status=son_status, attempts=deneme,
                         elapsed_s=clock() - t0) from son_hata
