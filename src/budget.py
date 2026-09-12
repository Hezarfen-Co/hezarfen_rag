"""Maliyet tavanı — ENGELLEYİCİ bütçe kapısı (#79).

ÖLÇÜLEN DURUM (EXP-010/OPS-05): `costlog.record()` yalnız **yazıyordu**;
hiçbir çağıran dönüş değerine bakıp reddetmiyordu. Kullanıcı kotası, günlük
USD tavanı **yoktu**. Ölçülen sömürü yolları:

* `/rag/questions n=100000` → şema kabul etti, handler'a 100000 olarak ulaştı
* `/rag/chat options={"top_n":100000,"candidate_n":100000}` → **HTTP 200**
* **Tek istekte yüzlerce LLM çağrısı:** `scope.pages=[1..187]` özet →
  `Summarizer` 12 birimden fazlasında hiyerarşik moda geçiyor.

İlk ikisi `#48`'de Pydantic sınırlarıyla kapatıldı. Burada kalan iki katman:
**(a)** tek istekte yapılabilecek iş miktarının tavanı, **(b)** kullanıcı/gün
ve kurum/ay USD tavanı.

TASARIM KARARLARI

1. **Yumuşak alarm ≠ sert red.** Tek eşik yeterli değil: %80'de uyarmak
   operatöre zaman kazandırır, %100'de reddetmek ürünü korur. İkisi ayrı
   raporlanır ki "bütçe doldu" sürpriz olmasın.
2. **Kapı ÖNCE, çağrıdan önce.** Harcama gerçekleştikten sonra bakmak tavanı
   anlamsız kılar. Kapı istek yolunda, LLM çağrılmadan önce sorulur.
3. **Sayaç okuması ucuz olmalı.** `runs.jsonl` büyüdükçe her istekte baştan
   okumak O(n) olur (#84'ün konusu). Bu yüzden toplamlar bellekte tutulur ve
   yalnız süreç açılışında dosyadan ısıtılır.
4. **Bütçe hatası isteği DÜŞÜRMEZ.** Sayaç bozuksa/okunamazsa istek geçer ve
   uyarı yazılır: telemetri arızası ürünü durdurmamalı. Tavanın kendisi bir
   güvenlik kontrolü değil, maliyet kontrolüdür.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

# Tek istekte yapılabilecek iş
MAX_UNITS_PER_REQUEST = int(os.environ.get("RAG_MAX_UNITS_PER_REQUEST", "60"))
MAX_LLM_CALLS_PER_REQUEST = int(os.environ.get("RAG_MAX_LLM_CALLS_PER_REQUEST", "12"))
# Para tavanları (0 = kapalı)
USER_DAILY_USD = float(os.environ.get("RAG_USER_DAILY_USD", "0"))
TENANT_MONTHLY_USD = float(os.environ.get("RAG_TENANT_MONTHLY_USD", "0"))
SOFT_RATIO = float(os.environ.get("RAG_BUDGET_SOFT_RATIO", "0.8"))


@dataclass
class BudgetDecision:
    allowed: bool
    reason: str = ""
    scope: str = ""          # "user" | "tenant" | "request"
    spent_usd: float = 0.0
    limit_usd: float = 0.0
    soft: bool = False       # yumuşak eşik aşıldı mı (alarm; red DEĞİL)

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason, "scope": self.scope,
                "spent_usd": round(self.spent_usd, 6),
                "limit_usd": round(self.limit_usd, 6), "soft": self.soft}


def _day_key(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts if ts is not None else time.time()))


def _month_key(ts: float | None = None) -> str:
    return time.strftime("%Y-%m", time.gmtime(ts if ts is not None else time.time()))


@dataclass
class BudgetGate:
    """Kullanıcı/gün ve kurum/ay USD tavanı.

    DÜRÜST SINIR: süreç-içi sayaçtır. Çok-worker dağıtımda her worker kendi
    toplamını tutar; gerçek tavan paylaşımlı bir sayaçta (ör. veritabanı)
    olmalıdır (#86). Burada amaç tek bir kullanıcının ya da bozuk bir
    döngünün bütçeyi tek başına bitirmesini engellemek.
    """
    user_daily_usd: float = None            # type: ignore[assignment]
    tenant_monthly_usd: float = None        # type: ignore[assignment]
    soft_ratio: float = None                # type: ignore[assignment]
    _user: dict = field(default_factory=dict)
    _tenant: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        if self.user_daily_usd is None:
            self.user_daily_usd = USER_DAILY_USD
        if self.tenant_monthly_usd is None:
            self.tenant_monthly_usd = TENANT_MONTHLY_USD
        if self.soft_ratio is None:
            self.soft_ratio = SOFT_RATIO

    # -- kayıt ----------------------------------------------------------
    def record(self, usd: float, *, user: str | None = None,
               tenant: str | None = None, ts: float | None = None) -> None:
        if usd <= 0:
            return
        with self._lock:
            if user:
                k = (user, _day_key(ts))
                self._user[k] = self._user.get(k, 0.0) + usd
            if tenant:
                k = (tenant, _month_key(ts))
                self._tenant[k] = self._tenant.get(k, 0.0) + usd

    def spent(self, *, user: str | None = None, tenant: str | None = None,
              ts: float | None = None) -> float:
        with self._lock:
            if user:
                return self._user.get((user, _day_key(ts)), 0.0)
            if tenant:
                return self._tenant.get((tenant, _month_key(ts)), 0.0)
            return 0.0

    # -- kapı -----------------------------------------------------------
    def check(self, *, user: str | None = None, tenant: str | None = None,
              ts: float | None = None) -> BudgetDecision:
        """Harcamadan ÖNCE sorulur. Tavan aşıldıysa `allowed=False`."""
        soft = False
        for kapsam, ad, limit in (("user", user, self.user_daily_usd),
                                  ("tenant", tenant, self.tenant_monthly_usd)):
            if not ad or limit <= 0:
                continue
            harcanan = self.spent(**{kapsam: ad}, ts=ts)
            if harcanan >= limit:
                return BudgetDecision(False, "budget_exceeded", kapsam,
                                      harcanan, limit, soft=True)
            if harcanan >= limit * self.soft_ratio:
                soft = True
        return BudgetDecision(True, "", "", soft=soft)

    def snapshot(self) -> dict:
        with self._lock:
            return {"user_daily_usd": self.user_daily_usd,
                    "tenant_monthly_usd": self.tenant_monthly_usd,
                    "soft_ratio": self.soft_ratio,
                    "izlenen_kullanici": len(self._user),
                    "izlenen_kurum": len(self._tenant)}


def estimate_llm_calls(n_units: int, max_units_per_group: int = 12) -> int:
    """Bir özet isteğinin kaç LLM çağrısı yapacağını ÖNCEDEN hesaplar.

    `Summarizer` `max_units_per_group`'u aşan kapsamda özyinelemeli hiyerarşik
    moda geçer: her grup bir ara-özet, sonra ara-özetler yeniden gruplanır.
    Ölçülen sömürü: `scope.pages=[1..187]` → tek HTTP isteğinde onlarca-yüzlerce
    çağrı. Bu fonksiyon o sayıyı istek kabul edilmeden önce verir.
    """
    if n_units <= 0:
        return 0
    if n_units <= max_units_per_group:
        return 1
    toplam = 0
    seviye = -(-n_units // max_units_per_group)     # tavan bölme
    toplam += seviye
    while seviye > 1:
        seviye = -(-seviye // max_units_per_group)
        toplam += seviye
    return toplam


def check_request_size(n_units: int, *, max_units: int | None = None,
                       max_calls: int | None = None,
                       max_units_per_group: int = 12) -> BudgetDecision:
    """Tek isteğin iş büyüklüğü tavanı (para tavanından BAĞIMSIZ).

    Para tavanı ayda bir dolar; bu kapı **her istekte** çalışır ve tek bir
    isteğin yüzlerce LLM çağrısına dönüşmesini engeller.
    """
    u = MAX_UNITS_PER_REQUEST if max_units is None else max_units
    c = MAX_LLM_CALLS_PER_REQUEST if max_calls is None else max_calls
    if u > 0 and n_units > u:
        return BudgetDecision(False, "scope_too_large", "request",
                              spent_usd=float(n_units), limit_usd=float(u))
    cagri = estimate_llm_calls(n_units, max_units_per_group)
    if c > 0 and cagri > c:
        return BudgetDecision(False, "scope_too_large", "request",
                              spent_usd=float(cagri), limit_usd=float(c))
    return BudgetDecision(True)
