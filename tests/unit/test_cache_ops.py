"""#83 (EXP-010/OPS-11) — cache üretime bağlandı: WAL + boyut tavanı + eviction.

ÖLÇÜLEN DURUM:
* `build_service`'te `Generator(...)` çağrısında **`response_cache` verilmiyordu**
  ve `BGEM3Embedder()` `cache=None` ile kuruluyordu. Yani **üretimde her soru
  LLM'e gidiyordu**; `OPTIMIZATION.md §C`'deki maliyet kazancı hiç gerçekleşmiyordu.
* `PRAGMA journal_mode` = **`delete`** (WAL kapalı) → her yazım okuyucuları
  bloke ediyordu.
* Boyut tavanı / eviction API'si **yoktu**. Ölçüldü: 10 süreç × 300 × 200 KB
  yazım → 0 hata ama DB **602 MB**'a çıktı ve hiçbir şey küçültmedi.
"""
import os
import tempfile
import threading
import unittest

from src.cache.base import SQLiteCache


class WalTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.yol = os.path.join(self.d, "c.db")

    def test_file_backed_cache_uses_wal(self):
        c = SQLiteCache(self.yol)
        mod = c._conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mod.lower(), "wal")

    def test_busy_timeout_is_set(self):
        c = SQLiteCache(self.yol, busy_timeout_ms=7000)
        self.assertEqual(c._conn.execute("PRAGMA busy_timeout").fetchone()[0], 7000)

    def test_memory_cache_still_works(self):
        """`:memory:` için WAL anlamsızdır; sessizce atlanmalı, patlamamalı."""
        c = SQLiteCache(":memory:")
        c.set("k", "v", ttl=60)
        self.assertEqual(c.get("k"), "v")


class EvictionTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.yol = os.path.join(self.d, "c.db")

    def test_size_is_reported(self):
        c = SQLiteCache(self.yol)
        once = c.size_bytes()
        for i in range(200):
            c.set(f"k{i}", b"x" * 2000, ttl=3600)
        self.assertGreater(c.size_bytes(), once)

    def test_eviction_brings_size_under_the_ceiling(self):
        """602 MB'a çıkıp küçülmeyen DB'nin düzeltmesi."""
        tavan = 120 * 1024
        c = SQLiteCache(self.yol, max_bytes=tavan)
        for i in range(400):
            c.set(f"k{i}", b"x" * 2000, ttl=3600)
        self.assertGreater(c.size_bytes(), tavan)
        c.evict_lru()
        self.assertLessEqual(c.size_bytes(), tavan)

    def test_cache_still_usable_after_eviction(self):
        c = SQLiteCache(self.yol, max_bytes=80 * 1024)
        for i in range(300):
            c.set(f"k{i}", b"x" * 2000, ttl=3600)
        c.evict_lru()
        c.set("yeni", "deger", ttl=60)
        self.assertEqual(c.get("yeni"), "deger")

    def test_expired_rows_go_first(self):
        """Süresi dolmuşlar bedava kazançtır; taze veriden önce atılmalı."""
        saat = [1000.0]
        c = SQLiteCache(self.yol, max_bytes=1, clock=lambda: saat[0])
        c.set("eski", b"x" * 1000, ttl=10)
        saat[0] = 2000.0
        c.set("taze", b"y" * 1000, ttl=3600)
        c.evict_lru()
        self.assertIsNone(c.get("eski"))

    def test_no_ceiling_means_no_eviction(self):
        c = SQLiteCache(self.yol)                  # max_bytes yok
        for i in range(50):
            c.set(f"k{i}", b"x" * 1000, ttl=3600)
        self.assertEqual(c.evict_lru(), 0)
        self.assertEqual(c.get("k0"), b"x" * 1000)

    def test_concurrent_writes_do_not_corrupt(self):
        """Eşzamanlı 8 yazar — WAL'in asıl sınavı."""
        c = SQLiteCache(self.yol, max_bytes=0)
        hatalar = []

        def yaz(n):
            try:
                for i in range(50):
                    c.set(f"t{n}-{i}", b"z" * 500, ttl=3600)
            except Exception as e:                  # noqa: BLE001
                hatalar.append(repr(e))

        ths = [threading.Thread(target=yaz, args=(n,)) for n in range(8)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(hatalar, [])
        self.assertEqual(c.get("t0-0"), b"z" * 500)


class ProductionWiringTests(unittest.TestCase):
    """Cache üretimde GERÇEKTEN bağlı mı — sözleşme testi."""

    def test_build_service_passes_the_response_cache(self):
        import inspect
        from src.service import http_app
        kaynak = inspect.getsource(http_app.build_service)
        self.assertIn("response_cache=response_cache", kaynak)

    def test_cache_is_off_by_default(self):
        """Açmak bir davranış değişikliğidir; #77'ye göre `corpus_version`
        olmadan tehlikelidir. Varsayılan kapalı olmalı."""
        from src.service import http_app
        self.assertEqual(http_app.CACHE_PATH, "")

    def test_ceiling_default_is_bounded(self):
        from src.service import http_app
        self.assertGreater(http_app.CACHE_MAX_BYTES, 0)
        self.assertLessEqual(http_app.CACHE_MAX_BYTES, 4 * 1024 ** 3)

    def test_corpus_version_is_filled_by_build_service(self):
        """#77 ile birlikte: sürümsüz cache devre dışı kalır, yani
        `build_service` sürümü doldurmazsa cache hiç çalışmaz."""
        import inspect
        from src.service import http_app
        kaynak = inspect.getsource(http_app.build_service)
        self.assertIn("corpus_version=cv", kaynak)


if __name__ == "__main__":
    unittest.main()
