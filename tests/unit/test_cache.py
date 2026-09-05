"""Cache katmanı birim testleri (maliyet optimizasyonu) — bkz.
docs/OPTIMIZATION.md §C, docs/reports/RES-002-ragart-analysis.md §4.

Model/ağ GEREKMEZ: SQLiteCache bellek-içi (`:memory:`) çalışır; TTL testleri
gerçek `time.sleep` yerine enjekte edilen sahte saat (`_FakeClock`) ile
ilerletilir (hızlı + gürültüsüz). pass-bias YASAK: TTL=0/negatif, bozuk cache
kaydı (deserialize hatası) ve boş sorgu gibi kenar durumlar da kapsanır."""
from __future__ import annotations

import unittest

from src.cache import (CacheStats, DEFAULT_TTL_SECONDS, EmbeddingCache,
                       ResponseCache, SQLiteCache, canonical_key)


class _FakeClock:
    """`time.time` yerine enjekte edilebilen, elle ilerletilen sahte saat."""

    def __init__(self, start: float = 1_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


# --------------------------------------------------------------------------- SQLiteCache

class SQLiteCacheBasicTests(unittest.TestCase):
    def test_set_get_roundtrip(self):
        c = SQLiteCache(":memory:")
        c.set("k1", {"a": 1, "b": [1, 2, 3]})
        self.assertEqual(c.get("k1"), {"a": 1, "b": [1, 2, 3]})

    def test_miss_on_unknown_key(self):
        c = SQLiteCache(":memory:")
        self.assertIsNone(c.get("bilinmeyen"))

    def test_overwrite_existing_key(self):
        c = SQLiteCache(":memory:")
        c.set("k", "v1")
        c.set("k", "v2")
        self.assertEqual(c.get("k"), "v2")

    def test_delete(self):
        c = SQLiteCache(":memory:")
        c.set("k", "v")
        c.delete("k")
        self.assertIsNone(c.get("k"))

    def test_len_counts_rows(self):
        c = SQLiteCache(":memory:")
        c.set("a", 1)
        c.set("b", 2)
        self.assertEqual(len(c), 2)


class SQLiteCacheTTLTests(unittest.TestCase):
    """TTL/lazy-GC — zaman gerçek `sleep` OLMADAN `_FakeClock.advance` ile ilerletilir."""

    def test_ttl_none_never_expires(self):
        clock = _FakeClock()
        c = SQLiteCache(":memory:", clock=clock)
        c.set("k", "v", ttl=None)
        clock.advance(10_000_000)   # çok uzun süre geçse de
        self.assertEqual(c.get("k"), "v")

    def test_ttl_expires_after_advance(self):
        clock = _FakeClock()
        c = SQLiteCache(":memory:", clock=clock)
        c.set("k", "v", ttl=5.0)
        self.assertEqual(c.get("k"), "v")     # süre dolmadan hâlâ hit
        clock.advance(5.001)
        self.assertIsNone(c.get("k"))         # süre dolunca miss (lazy GC)

    def test_ttl_not_yet_expired_is_hit(self):
        clock = _FakeClock()
        c = SQLiteCache(":memory:", clock=clock)
        c.set("k", "v", ttl=10.0)
        clock.advance(9.0)
        self.assertEqual(c.get("k"), "v")

    def test_expired_key_removed_from_store(self):
        clock = _FakeClock()
        c = SQLiteCache(":memory:", clock=clock)
        c.set("k", "v", ttl=1.0)
        clock.advance(2.0)
        c.get("k")                            # lazy GC tetiklenir
        self.assertEqual(len(c), 0)

    def test_gc_expired_removes_without_get(self):
        clock = _FakeClock()
        c = SQLiteCache(":memory:", clock=clock)
        c.set("k1", "v1", ttl=1.0)
        c.set("k2", "v2", ttl=None)
        clock.advance(2.0)
        removed = c.gc_expired()
        self.assertEqual(removed, 1)
        self.assertEqual(len(c), 1)
        self.assertEqual(c.get("k2"), "v2")


class SQLiteCacheEdgeCaseTests(unittest.TestCase):
    """Kenar durumlar: TTL=0/negatif, bozuk kayıt (deserialize hatası), boş anahtar."""

    def test_ttl_zero_is_not_cached(self):
        c = SQLiteCache(":memory:")
        c.set("k", "v", ttl=0)
        self.assertIsNone(c.get("k"))
        self.assertEqual(len(c), 0)

    def test_ttl_negative_is_not_cached(self):
        c = SQLiteCache(":memory:")
        c.set("k", "v", ttl=-5.0)
        self.assertIsNone(c.get("k"))

    def test_corrupted_record_graceful_miss(self):
        # deserialize (pickle.loads) hatası PATLAMADAN miss sayılmalı + kayıt silinmeli
        c = SQLiteCache(":memory:")
        c._conn.execute(
            "INSERT INTO kv_cache (key, value, expires_at, created_at) VALUES (?, ?, ?, ?)",
            ("bozuk", b"bu-gecerli-bir-pickle-blobu-degil", None, 0.0))
        c._conn.commit()
        result = c.get("bozuk")
        self.assertIsNone(result)
        self.assertEqual(c.stats.misses, 1)
        self.assertEqual(len(c), 0)   # bozuk kayıt temizlendi

    def test_empty_string_key_and_value(self):
        c = SQLiteCache(":memory:")
        c.set("", "")
        self.assertEqual(c.get(""), "")


class CacheStatsTests(unittest.TestCase):
    def test_hit_rate_computed_correctly(self):
        c = SQLiteCache(":memory:")
        c.set("k", "v")
        c.get("k")        # hit
        c.get("k")        # hit
        c.get("yok")       # miss
        self.assertEqual(c.stats.hits, 2)
        self.assertEqual(c.stats.misses, 1)
        self.assertAlmostEqual(c.stats.hit_rate, 2 / 3)

    def test_hit_rate_zero_when_no_access(self):
        stats = CacheStats()
        self.assertEqual(stats.hit_rate, 0.0)
        self.assertEqual(stats.total, 0)


# --------------------------------------------------------------------------- EmbeddingCache

class EmbeddingCacheTests(unittest.TestCase):
    def test_miss_then_set_then_hit(self):
        ec = EmbeddingCache(SQLiteCache(":memory:"), model="bge-m3")
        self.assertIsNone(ec.get("merhaba"))
        ec.set("merhaba", [0.1, 0.2, 0.3])
        self.assertEqual(ec.get("merhaba"), [0.1, 0.2, 0.3])

    def test_different_model_different_key_no_cross_hit(self):
        backend = SQLiteCache(":memory:")
        ec_a = EmbeddingCache(backend, model="model-a")
        ec_b = EmbeddingCache(backend, model="model-b")
        ec_a.set("aynı metin", [1.0, 2.0])
        self.assertIsNone(ec_b.get("aynı metin"), "farklı model aynı cache anahtarını PAYLAŞMAMALI")

    def test_get_many_batch_miss_merge(self):
        ec = EmbeddingCache(SQLiteCache(":memory:"), model="bge-m3")
        ec.set("var-olan", [9.0])
        hits, misses = ec.get_many(["var-olan", "yeni-1", "yeni-2"])
        self.assertEqual(hits, {"var-olan": [9.0]})
        self.assertEqual(misses, ["yeni-1", "yeni-2"])

        # embedder yalnız misses'i modele verir, sonucu toptan cache'e yazar
        ec.set_many({"yeni-1": [1.0], "yeni-2": [2.0]})
        hits2, misses2 = ec.get_many(["var-olan", "yeni-1", "yeni-2"])
        self.assertEqual(misses2, [])
        self.assertEqual(hits2, {"var-olan": [9.0], "yeni-1": [1.0], "yeni-2": [2.0]})

    def test_set_many_accepts_list_of_pairs(self):
        ec = EmbeddingCache(SQLiteCache(":memory:"), model="bge-m3")
        ec.set_many([("a", [1.0]), ("b", [2.0])])
        self.assertEqual(ec.get("a"), [1.0])
        self.assertEqual(ec.get("b"), [2.0])

    def test_default_ttl_is_infinite(self):
        clock = _FakeClock()
        ec = EmbeddingCache(SQLiteCache(":memory:", clock=clock), model="bge-m3")
        ec.set("k", [1.0])
        clock.advance(10_000_000)
        self.assertEqual(ec.get("k"), [1.0])   # TTL sonsuz -> asla süresi dolmaz

    def test_stats_delegates_to_backend(self):
        ec = EmbeddingCache(SQLiteCache(":memory:"), model="bge-m3")
        ec.get("yok")
        ec.set("k", [1.0])
        ec.get("k")
        self.assertEqual(ec.stats.misses, 1)
        self.assertEqual(ec.stats.hits, 1)


# --------------------------------------------------------------------------- ResponseCache

class ResponseCacheKeyTests(unittest.TestCase):
    """RagArt dersi: cevabı değiştirebilecek HER parametre anahtara girmeli —
    farklı role/top_n/model/ders/candidate_n FARKLI anahtar üretmeli."""

    def test_same_params_same_key(self):
        k1 = canonical_key(query="DNA nedir?", role="student", model="deepseek-chat",
                           top_n=6, candidate_n=40, ders="biyoloji")
        k2 = canonical_key(query="DNA nedir?", role="student", model="deepseek-chat",
                           top_n=6, candidate_n=40, ders="biyoloji")
        self.assertEqual(k1, k2)

    def test_different_role_different_key(self):
        base = dict(query="DNA nedir?", model="deepseek-chat", top_n=6,
                   candidate_n=40, ders="biyoloji")
        k_student = canonical_key(role="student", **base)
        k_teacher = canonical_key(role="teacher", **base)
        self.assertNotEqual(k_student, k_teacher)

    def test_different_top_n_different_key(self):
        base = dict(query="DNA nedir?", role="student", model="deepseek-chat",
                   candidate_n=40, ders="biyoloji")
        self.assertNotEqual(canonical_key(top_n=6, **base), canonical_key(top_n=8, **base))

    def test_different_model_different_key(self):
        base = dict(query="DNA nedir?", role="student", top_n=6, candidate_n=40, ders="biyoloji")
        self.assertNotEqual(canonical_key(model="deepseek-chat", **base),
                            canonical_key(model="deepseek-reasoner", **base))

    def test_different_ders_different_key(self):
        base = dict(query="DNA nedir?", role="student", model="deepseek-chat",
                   top_n=6, candidate_n=40)
        self.assertNotEqual(canonical_key(ders="biyoloji", **base), canonical_key(ders="fizik", **base))

    def test_empty_query_produces_stable_non_crashing_key(self):
        k1 = canonical_key(query="", role="", model="", top_n=0, candidate_n=0, ders="")
        k2 = canonical_key(query="", role="", model="", top_n=0, candidate_n=0, ders="")
        self.assertEqual(k1, k2)
        self.assertTrue(len(k1) > 0)


class ResponseCacheStoreTests(unittest.TestCase):
    def test_miss_then_set_then_hit_returns_equal_payload(self):
        rc = ResponseCache(SQLiteCache(":memory:"))
        key_kwargs = dict(query="DNA nedir?", role="student", model="deepseek-chat",
                          top_n=6, candidate_n=40, ders="biyoloji")
        self.assertIsNone(rc.get(**key_kwargs))

        payload = {"text": "DNA çift sarmaldır [1].", "cost_usd": 0.0042}
        rc.set(payload, **key_kwargs)
        self.assertEqual(rc.get(**key_kwargs), payload)

    def test_different_role_is_a_miss(self):
        rc = ResponseCache(SQLiteCache(":memory:"))
        key_kwargs = dict(query="DNA nedir?", role="student", model="deepseek-chat",
                          top_n=6, candidate_n=40, ders="biyoloji")
        rc.set({"text": "öğrenciye özel"}, **key_kwargs)

        teacher_kwargs = dict(key_kwargs, role="teacher")
        self.assertIsNone(rc.get(**teacher_kwargs))

    def test_default_ttl_is_one_hour(self):
        self.assertEqual(DEFAULT_TTL_SECONDS, 3600.0)

    def test_ttl_expiry_makes_it_a_miss_again(self):
        clock = _FakeClock()
        rc = ResponseCache(SQLiteCache(":memory:", clock=clock), ttl=60.0)
        key_kwargs = dict(query="q", role="", model="deepseek-chat", top_n=6,
                          candidate_n=40, ders="biyoloji")
        rc.set({"text": "cevap"}, **key_kwargs)
        self.assertIsNotNone(rc.get(**key_kwargs))
        clock.advance(61.0)
        self.assertIsNone(rc.get(**key_kwargs))

    def test_extra_field_distinguishes_key(self):
        # "gerekirse seçili kaynak" gibi ek ayırt edici alan (extra) anahtara girer
        rc = ResponseCache(SQLiteCache(":memory:"))
        base = dict(query="q", role="", model="m", top_n=1, candidate_n=1, ders="")
        rc.set({"text": "kaynak-A"}, extra={"selected_source": "A"}, **base)
        self.assertIsNone(rc.get(extra={"selected_source": "B"}, **base))
        self.assertEqual(rc.get(extra={"selected_source": "A"}, **base), {"text": "kaynak-A"})


if __name__ == "__main__":
    unittest.main()
