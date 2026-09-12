"""#77 (EXP-010/ACC-09 + OPS-01) — cache anahtarı sürüm taşımıyordu.

KOŞULARAK KANITLANMIŞ HATA: 1. çağrı `span_ids=['OLD#5.0']` döndü; re-ingest
sonrası 3. çağrı `cache_hit=True` ile **artık var olmayan span'a atıf**
döndürdü. Öğrenci atıfa tıklıyor, sayfa yok.

İki ayrı eksik vardı:
  (a) `corpus_version` varsayılanı `""` — korpus değişse de anahtar aynı.
      `http_app` dolduruyordu ama **kütüphane varsayılanı korumasızdı**;
      doğrudan `Generator` kuran her çağıran (eval, testler, gelecekteki
      servisler) aynı tuzağa düşüyordu.
  (b) `max_tokens`/`temperature` anahtara **hiç girmiyordu** — aynı soru farklı
      üretim ayarıyla sorulunca eski cevap dönüyordu.

YENİ SÖZLEŞME: `corpus_version` boşsa cache **devre dışı** + uyarı
(fail-closed). Sürümsüz cache, silinmiş kaynağa atıf demektir.
"""
import unittest
import warnings

from src.cache.response_cache import ResponseCache
from src.cache.base import SQLiteCache
from src.generate import Generator
from src.pricing import Usage


class _Chunk:
    def __init__(self, cid, text, span_ids, parent_id=None):
        self.chunk_id = cid
        self.text = text
        self.span_ids = span_ids
        self.parent_id = parent_id
        self.level = "child"


class _Retriever:
    def __init__(self, hits):
        self._h = hits

    def retrieve(self, query, top_k=20, **kw):
        return self._h[:top_k]


class _Reranker:
    def __init__(self, skor):
        self.skor = skor

    def rerank(self, query, items, top_k=None, normalize=True):
        out = sorted(((cid, self.skor.get(cid, 0.5)) for cid, _ in items),
                     key=lambda x: -x[1])
        return out[:top_k] if top_k else out


class _Chat:
    def __init__(self, text):
        self.text = text
        self.model = "stub"
        self.usage = Usage(input_cache_miss=10, output=5)
        self.latency_s = 0.0
        self.raw = {}


class _LLM:
    model = "stub"
    _api_key = "x"

    def __init__(self, text="Cevap [1]."):
        self.text = text
        self.calls = 0

    def chat(self, prompt, system=None, **kw):
        self.calls += 1
        return _Chat(self.text)


def _kur(llm, cache, *, corpus_version="", span="OLD#5.0"):
    chunks = {"c1": _Chunk("c1", "kaynak metni burada", [span])}
    span_meta = {span: {"page": 5, "bbox": (0, 0, 1, 1)}}
    return Generator(_Retriever([("c1", 1.0)]), _Reranker({"c1": 0.9}),
                     chunks, span_meta, llm, ders="biyoloji",
                     cost_recorder=lambda **kw: None, response_cache=cache,
                     corpus_version=corpus_version)


class VersionlessCacheIsDisabledTests(unittest.TestCase):
    def test_empty_version_disables_the_cache(self):
        """FAIL-CLOSED: sürümsüz cache eski/silinmiş kaynağa atıf döndürür."""
        llm = _LLM()
        gen = _kur(llm, ResponseCache(SQLiteCache(":memory:")), corpus_version="")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            a = gen.answer("soru")
            b = gen.answer("soru")
        self.assertEqual(llm.calls, 2, "sürümsüz cache yine de kullanıldı")
        self.assertFalse(a.cache_hit)
        self.assertFalse(b.cache_hit)

    def test_it_warns_loudly(self):
        llm = _LLM()
        gen = _kur(llm, ResponseCache(SQLiteCache(":memory:")), corpus_version="")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            gen.answer("soru")
        self.assertTrue(any(issubclass(x.category, RuntimeWarning) for x in w),
                        "sessizce devre dışı bırakıldı — operatör fark etmez")

    def test_version_enables_the_cache(self):
        llm = _LLM()
        gen = _kur(llm, ResponseCache(SQLiteCache(":memory:")), corpus_version="v1")
        gen.answer("soru")
        ikinci = gen.answer("soru")
        self.assertEqual(llm.calls, 1)
        self.assertTrue(ikinci.cache_hit)


class ReingestInvalidatesTests(unittest.TestCase):
    """Denetimin koşulan senaryosu: re-ingest sonrası eski span dönüyordu."""

    def test_new_corpus_version_does_not_serve_the_old_answer(self):
        cache = ResponseCache(SQLiteCache(":memory:"))
        llm = _LLM()
        eski = _kur(llm, cache, corpus_version="v1", span="OLD#5.0")
        a = eski.answer("soru")
        self.assertEqual(a.citations[0]["span_ids"], ["OLD#5.0"])

        # re-ingest: yeni sürüm, yeni span
        yeni = _kur(llm, cache, corpus_version="v2", span="NEW#7.0")
        b = yeni.answer("soru")
        self.assertFalse(b.cache_hit, "yeni sürümde ESKİ cevap döndü")
        self.assertEqual(b.citations[0]["span_ids"], ["NEW#7.0"])
        self.assertEqual(llm.calls, 2)

    def test_same_version_still_caches(self):
        cache = ResponseCache(SQLiteCache(":memory:"))
        llm = _LLM()
        for _ in range(3):
            _kur(llm, cache, corpus_version="v1").answer("soru")
        self.assertEqual(llm.calls, 1)


class GenerationParamsInTheKeyTests(unittest.TestCase):
    """`max_tokens`/`temperature` anahtara hiç girmiyordu."""

    def _gen(self, llm, cache):
        return _kur(llm, cache, corpus_version="v1")

    def test_different_temperature_is_a_different_answer(self):
        cache = ResponseCache(SQLiteCache(":memory:"))
        llm = _LLM()
        self._gen(llm, cache).answer("soru", temperature=0.0)
        self._gen(llm, cache).answer("soru", temperature=0.9)
        self.assertEqual(llm.calls, 2, "farklı sıcaklıkta eski cevap döndü")

    def test_different_max_tokens_is_a_different_answer(self):
        cache = ResponseCache(SQLiteCache(":memory:"))
        llm = _LLM()
        self._gen(llm, cache).answer("soru", max_tokens=100)
        self._gen(llm, cache).answer("soru", max_tokens=800)
        self.assertEqual(llm.calls, 2, "farklı max_tokens'ta eski cevap döndü")

    def test_identical_params_still_hit(self):
        cache = ResponseCache(SQLiteCache(":memory:"))
        llm = _LLM()
        self._gen(llm, cache).answer("soru", temperature=0.2, max_tokens=500)
        ikinci = self._gen(llm, cache).answer("soru", temperature=0.2, max_tokens=500)
        self.assertEqual(llm.calls, 1)
        self.assertTrue(ikinci.cache_hit)


class RoleAndScopeStillSeparateTests(unittest.TestCase):
    """Regresyon: sürüm eklenirken rol/ders ayrımı bozulmamalı (kasa sızıntısı)."""

    def test_different_subject_is_a_different_key(self):
        cache = ResponseCache(SQLiteCache(":memory:"))
        llm = _LLM()
        a = _kur(llm, cache, corpus_version="v1")
        a.ders = "biyoloji"
        a.answer("soru")
        b = _kur(llm, cache, corpus_version="v1")
        b.ders = "fizik"
        b.answer("soru")
        self.assertEqual(llm.calls, 2, "başka dersin cevabı cache'ten döndü")


if __name__ == "__main__":
    unittest.main()
