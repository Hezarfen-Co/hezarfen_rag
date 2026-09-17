"""#75 — İNDEKS ÖNBELLEĞİ ve DÜRÜST `/ready`.

ÜÇ İDDİA SINANIR:
1. `disk_cache` gömme çıktısını diske yazıp AYNEN geri okur; anahtar içerik
   ya da model değişince değişir; bozuk/eksik dosya bir HATA değil ISKADIR.
2. `/ready` "sağlayıcı hazır" ile "korpus KURULU"yu ayırır (`hazir_tur`).
   #75/OPS: konteyner yeniden yaratıldığında indeks kaybolur; readiness bunu
   `korpus_hazir=False` ile göstermeli, "ready" diye YALAN söylememeli.
3. `MultiCorpusService.generator` korpus TANIMLI olduğu için değil, KURULU
   olduğu için dolu döner (eskiden `object()` fallback'i readiness'ı yeşil
   yakıyordu; sorular ise `service_warming_up` dönüyordu).

Korpus fixture'ı GEREKMEZ: önbellek saf, `/ready` ise sahte servisle ölçülür.
"""
import os
import tempfile
import unittest

import numpy as np

from src.index import disk_cache


class DiskCacheTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = self.d.name
        self.addCleanup(self.d.cleanup)

    @staticmethod
    def _ornek(n=3, dim=4):
        ids = [f"doc#{i}" for i in range(n)]
        vecs = np.arange(n * dim, dtype=np.float32).reshape(n, dim)
        sparse = [{"1": 0.5}, {}, {"2": 1.0}][:n]
        return ids, vecs, sparse

    def test_round_trip_is_exact(self):
        ids, vecs, sparse = self._ornek()
        key = disk_cache.cache_key("doc", ["a", "b", "c"], "sig")
        self.assertIsNotNone(disk_cache.save(self.root, "doc", key, ids, vecs, sparse))
        got = disk_cache.load(self.root, "doc", key, dim=4, n=3)
        self.assertIsNotNone(got)
        g_ids, g_vecs, g_sparse = got
        self.assertEqual(g_ids, ids)
        self.assertTrue(np.array_equal(g_vecs, vecs))
        self.assertEqual(g_sparse, sparse)

    def test_key_is_content_and_model_derived(self):
        a = disk_cache.cache_key("doc", ["bir metin"], "voyage|m|1024")
        self.assertNotEqual(a, disk_cache.cache_key("doc", ["başka metin"], "voyage|m|1024"))
        self.assertNotEqual(a, disk_cache.cache_key("doc", ["bir metin"], "cohere|m|1024"))
        self.assertNotEqual(a, disk_cache.cache_key("baska", ["bir metin"], "voyage|m|1024"))
        self.assertEqual(a, disk_cache.cache_key("doc", ["bir metin"], "voyage|m|1024"))

    def test_empty_root_disables_cache(self):
        ids, vecs, sparse = self._ornek()
        key = disk_cache.cache_key("doc", ["x"], "sig")
        self.assertIsNone(disk_cache.save("", "doc", key, ids, vecs, sparse))
        self.assertIsNone(disk_cache.load("", "doc", key, dim=4, n=3))
        self.assertEqual(disk_cache.cache_root({}), "")

    def test_missing_and_corrupt_are_misses_not_errors(self):
        key = disk_cache.cache_key("doc", ["x"], "sig")
        self.assertIsNone(disk_cache.load(self.root, "doc", key, dim=4, n=3))
        with open(os.path.join(self.root, "doc." + key + ".npz"), "wb") as fh:
            fh.write(b"bu bir npz degil")
        self.assertIsNone(disk_cache.load(self.root, "doc", key, dim=4, n=3))

    def test_shape_mismatch_is_a_miss(self):
        """n ya da boyut tutmuyorsa ISKALANIR — yanlış vektörle indeks kurulmaz."""
        ids, vecs, sparse = self._ornek()
        key = disk_cache.cache_key("doc", ["a", "b", "c"], "sig")
        disk_cache.save(self.root, "doc", key, ids, vecs, sparse)
        self.assertIsNone(disk_cache.load(self.root, "doc", key, dim=1024, n=3))
        self.assertIsNone(disk_cache.load(self.root, "doc", key, dim=4, n=2))


try:
    from fastapi.testclient import TestClient
    from src.service.http_app import _LazyService, create_app
    _HAS_FASTAPI = True
except Exception:                                   # pragma: no cover
    _HAS_FASTAPI = False


class _Gercek:
    generator = object()
    doc = object()
    question_gen = object()
    summarizer = object()

    def chat(self, req):
        return {"text": "x", "abstained": False, "reason": ""}

    def summarize(self, req):
        return {"text": "x", "abstained": False, "reason": ""}

    def generate_questions(self, req):
        return {"items": [], "abstained": False, "reason": ""}


@unittest.skipUnless(_HAS_FASTAPI, "fastapi yok")
class ReadinessShapeTests(unittest.TestCase):
    def test_before_corpus_build_readiness_declares_provider_only(self):
        lazy = _LazyService()
        c = TestClient(create_app(lazy))
        r = c.get("/ready")
        b = r.json()
        self.assertEqual(r.status_code, 503)
        self.assertFalse(b["korpus_hazir"])
        self.assertEqual(b["hazir_tur"], "yok")

    def test_after_corpus_build_readiness_is_full(self):
        lazy = _LazyService()
        c = TestClient(create_app(lazy))
        lazy.ata(_Gercek())
        r = c.get("/ready")
        b = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(b["korpus_hazir"])
        self.assertEqual(b["hazir_tur"], "tam")


class MultiCorpusReadinessTests(unittest.TestCase):
    def test_generator_is_none_until_a_corpus_is_loaded(self):
        """TANIMLI != KURULU: hazırlık iddiası kurulu korpusa bağlı olmalı."""
        from src.service.multi import MultiCorpusService
        s = MultiCorpusService(["10/biyoloji"], school="okul-a", shared=object())
        s._specs = {k: __file__ for k in s._specs}   # dosya kontrolünü aş
        self.assertFalse(s.korpus_hazir)
        self.assertIsNone(s.generator)


if __name__ == "__main__":
    unittest.main()
