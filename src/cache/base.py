"""Cache katmanı — maliyet optimizasyonu (bkz. docs/OPTIMIZATION.md §C,
docs/reports/RES-002-ragart-analysis.md §4).

RagArt'tan uyarlanmış: 3-katman SQLite cache (Response/Embedding). RagArt'ın
BOŞLUĞU — canlı token/$ telemetrisi yoktu; biz `src/costlog.py` ile her
DeepSeek çağrısında GERÇEK maliyeti ölçeriz (bkz. src/generate/generator.py
cache entegrasyonu: cache hit -> LLM hiç çağrılmaz -> maliyet 0, bu ÖLÇÜLÜR).

Bu modül: `BaseCache` arayüzü + zero-dep `SQLiteCache` (stdlib sqlite3 +
pickle; ekstra bağımlılık yok). Değer tipi keyfi (Python nesnesi) — pickle ile
blob'a serialize edilir. TTL saniye cinsinden; `None` = sonsuz (asla süresi
dolmaz). GC **lazy**: süresi geçmiş kayıt yalnız `get()` sırasında rastlanınca
silinir (arka plan thread'i YOK — zero-dep ilkesine uygun); `gc_expired()` ile
elle toplu temizlik de yapılabilir.

**Bilinen sınırlar (fazın dışında, gördüğün eksikler raporunda tekrarlanır):**
- Tek `threading.Lock` ile korunur — çoklu SÜREÇ (process) arası kilit YOK
  (yalnız aynı süreç içi thread-safety). Üretimde çoklu worker/process
  senaryosunda WAL modu + dosya-seviyesi kilit değerlendirilmeli.
- Lazy GC yalnız erişilen anahtarları temizler; hiç erişilmeyen süresi geçmiş
  kayıtlar `gc_expired()` elle çağrılmadıkça diskte kalır (sınırsız büyüme
  riski — üretimde periyodik `gc_expired()` çağrısı/cron gerekir).
"""
from __future__ import annotations

import pickle
import sqlite3
import threading
import time
from dataclasses import dataclass


@dataclass
class CacheStats:
    """Bir cache backend'inin hit/miss sayaçları (maliyet-kazancı telemetrisi)."""
    hits: int = 0
    misses: int = 0

    @property
    def total(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total if self.total else 0.0

    def record_hit(self) -> None:
        self.hits += 1

    def record_miss(self) -> None:
        self.misses += 1


class BaseCache:
    """Cache arayüzü — backend'ler (SQLite, ileride başka bir şey) bunu uygular.
    `EmbeddingCache`/`ResponseCache` bu arayüze göre yazılır, backend'e bağımlı
    değildir (test'te de gerçek SQLite yerine bellek-içi backend enjekte edilebilir)."""

    def get(self, key: str):
        raise NotImplementedError

    def set(self, key: str, value, ttl: float | None = None) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    @property
    def stats(self) -> CacheStats:
        raise NotImplementedError


_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv_cache (
    key TEXT PRIMARY KEY,
    value BLOB NOT NULL,
    expires_at REAL,
    created_at REAL NOT NULL
)
"""


class SQLiteCache(BaseCache):
    """stdlib `sqlite3` + `pickle` — zero-dep key -> değer(blob) cache.

    `path`: dosya yolu ya da `":memory:"` (varsayılan — testte tempfile de
    verilebilir, üretimde kalıcı dosya yolu). `clock`: zaman kaynağı (testte
    TTL'i gerçek `time.sleep` OLMADAN ilerletmek için enjekte edilebilir)."""

    def __init__(self, path: str = ":memory:", *, clock=time.time,
                 max_bytes: int | None = None, busy_timeout_ms: int = 5000):
        """`max_bytes`: yaklaşık boyut tavanı (0/None = sınırsız).

        M4-9 (#83, EXP-010/OPS-11) — ÖLÇÜLEN İKİ SORUN:

        1. **WAL kapalıydı.** `PRAGMA journal_mode` = `delete`; yani her yazım
           tüm okuyucuları bloke ediyordu. Çok-worker'a geçmeden bile aynı
           süreçteki eşzamanlı istekler birbirini bekliyordu.
        2. **Boyut tavanı ve eviction YOKTU.** Ölçüldü: 10 süreç × 300 × 200 KB
           yazım → 0 hata ama DB **602 MB**'a çıktı ve hiçbir şey küçültmedi.
           Süresi dolmuş satırlar bile yer kaplamaya devam ediyordu.

        `journal_mode=WAL` bellek-içi (":memory:") veritabanlarında anlamsızdır;
        orada sessizce atlanır.
        """
        self._clock = clock
        self._lock = threading.Lock()
        self._path = path
        self.max_bytes = int(max_bytes or 0)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        with self._lock:
            self._conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
            if path != ":memory:":
                # WAL: okuyucular yazarı beklemez. Dosya-tabanlı DB'de şart.
                self._conn.execute("PRAGMA journal_mode = WAL")
                self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute(_SCHEMA)
            self._conn.commit()
        self._stats = CacheStats()

    # -- boyut yönetimi --------------------------------------------------
    def size_bytes(self) -> int:
        """Veritabanının yaklaşık disk boyutu."""
        with self._lock:
            row = self._conn.execute(
                "SELECT page_count * page_size FROM "
                "pragma_page_count(), pragma_page_size()").fetchone()
        return int(row[0]) if row else 0

    def evict_lru(self, target_bytes: int | None = None) -> int:
        """Boyut tavanını aşınca EN ESKİ yazılanları atar. Döner: silinen satır.

        Basit LRU: `created_at` sırasına göre. Erişim zamanı tutulmuyor —
        tutmak her okumada yazım demek ve WAL'e rağmen maliyetli. Bu yüzden
        "en eski yazılan" yaklaşımı seçildi; kabul edilebilir çünkü cevap
        cache'inde TTL zaten kısa (1 saat).
        """
        tavan = int(target_bytes or self.max_bytes or 0)
        if tavan <= 0:
            return 0
        silinen = 0
        # Önce süresi dolmuşlar (bedava kazanç), sonra en eskiler.
        silinen += self.gc_expired()
        while self.size_bytes() > tavan:
            with self._lock:
                cur = self._conn.execute(
                    "DELETE FROM kv_cache WHERE key IN ("
                    "  SELECT key FROM kv_cache ORDER BY created_at ASC LIMIT 200)")
                self._conn.commit()
                n = cur.rowcount or 0
            if n == 0:
                break                       # boşaltacak bir şey kalmadı
            silinen += n
            with self._lock:
                self._conn.execute("VACUUM")
        return silinen

    @property
    def stats(self) -> CacheStats:
        return self._stats

    def _now(self) -> float:
        return self._clock()

    def get(self, key: str):
        with self._lock:
            row = self._conn.execute(
                "SELECT value, expires_at FROM kv_cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                self._stats.record_miss()
                return None
            value_blob, expires_at = row
            if expires_at is not None and expires_at <= self._now():
                # süresi geçmiş -> lazy GC: bu kaydı sil + miss say
                self._conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
                self._conn.commit()
                self._stats.record_miss()
                return None
            try:
                value = pickle.loads(value_blob)
            except Exception:
                # bozuk/deserialize-edilemeyen kayıt -> PATLAMADAN miss say + sil
                # (ör. pickle formatı değişmiş, dosya bozulmuş)
                self._conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
                self._conn.commit()
                self._stats.record_miss()
                return None
            self._stats.record_hit()
            return value

    def set(self, key: str, value, ttl: float | None = None) -> None:
        # TTL=0 veya negatif: kayıt anında "geçmiş" sayılır -> YAZMA, ama VARSA eski
        # değeri SİL. (AUDIT EXP-007 #K2: eskiden bare return önceden yazılmış bir
        # değeri BIRAKIYORDU → sonraki get() stale HIT dönüyordu; docstring'in "her
        # zaman miss" sözüyle çelişiyordu. Artık gerçekten miss döner.)
        if ttl is not None and ttl <= 0:
            self.delete(key)
            return
        now = self._now()
        expires_at = (now + ttl) if ttl is not None else None
        blob = pickle.dumps(value)
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv_cache (key, value, expires_at, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "expires_at=excluded.expires_at, created_at=excluded.created_at",
                (key, blob, expires_at, now))
            self._conn.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
            self._conn.commit()

    def gc_expired(self) -> int:
        """Süresi geçmiş TÜM kayıtları elle temizle (lazy GC'nin dışında,
        periyodik bakım için); silinen satır sayısını döndürür."""
        now = self._now()
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM kv_cache WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
            self._conn.commit()
            return cur.rowcount

    def __len__(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM kv_cache").fetchone()
            return row[0] if row else 0

    def close(self) -> None:
        self._conn.close()
