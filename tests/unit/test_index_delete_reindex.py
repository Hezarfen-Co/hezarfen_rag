"""#M3-10 / #M4-2+#M4-3 (EVAL-16, ACC-09, O-02, O-03) — SİL → YENİDEN İNDEKSLE.

ÖLÇÜLEN DURUM: silme kodu HİÇ YOKTU; `DenseIndex`/`BM25Index`/`SparseIndex`
silme API'si taşımıyordu. `tests/integration/test_source_deletion.py` artık
indeks KATMANINI ölçüyor (üç indeks temizleniyor mu, yayılım tam mı, kayıt
tutuluyor mu).

BU DOSYA ÜRÜN DÖNGÜSÜNÜ ölçüyor: öğretmen kaynağı siler ya da günceller,
ARDINDAN öğrenci soru sorar. Kritik soru şu: öğrenci artık var olmayan bir
sayfaya atıf alıyor mu? Koşularak kanıtlanmış hata (ACC-09): re-ingest
sonrası 3. çağrı `cache_hit=True` ile **silinmiş span'a atıf** döndürüyordu.
Öğrenci atıfa tıklıyor, sayfa yok — ürün yalan söylemiş oluyor.
"""
import unittest
import warnings

from src.cache.base import SQLiteCache
from src.cache.response_cache import ResponseCache
from src.corpus.deletion import bump_version, delete_source
from src.generate import Generator
from tests.unit.test_cache_invalidation import _Chunk, _LLM, _Reranker, _Retriever


def _generator(llm, cache, *, chunks, hits, corpus_version):
    span_meta = {}
    for c in chunks.values():
        for s in c.span_ids:
            span_meta[s] = {"page": int(s.split("#")[1].split(".")[0]),
                            "bbox": (0, 0, 1, 1)}
    return Generator(_Retriever(hits), _Reranker({c: 0.9 for c in chunks}),
                     chunks, span_meta, llm, ders="biyoloji",
                     cost_recorder=lambda **kw: None, response_cache=cache,
                     corpus_version=corpus_version)


class _Index:
    """Silme yayılımını izleyen asgari indeks taklidi."""

    def __init__(self, doc_ids):
        self.docs = set(doc_ids)
        self.deleted = []

    def delete(self, doc_id):
        self.deleted.append(doc_id)
        if doc_id not in self.docs:
            return 0
        self.docs.discard(doc_id)
        return 1

    def doc_ids(self):
        return sorted(self.docs)


class ReindexCycleTests(unittest.TestCase):
    """Sil → sürümü yükselt → yeniden indeksle → sor."""

    def setUp(self):
        self.cache = ResponseCache(SQLiteCache(":memory:"))
        self.query = "fotosentez nedir"

    def test_old_answer_is_not_served_after_a_version_bump(self):
        eski = {"c1": _Chunk("c1", "eski metin", ["OLD#5.0"])}
        llm = _LLM("Cevap [1].")
        gen = _generator(llm, self.cache, chunks=eski, hits=[("c1", 1.0)],
                         corpus_version="v1")
        ilk = gen.answer(self.query)
        self.assertEqual(ilk.citations[0]["span_ids"], ["OLD#5.0"])
        self.assertEqual(llm.calls, 1)
        gen.answer(self.query)                      # 2. çağrı cache'ten
        self.assertEqual(llm.calls, 1)

        # Öğretmen kaynağı değiştirdi: yeni sürüm, yeni span'lar.
        yeni = {"c2": _Chunk("c2", "yeni metin", ["NEW#7.0"])}
        gen2 = _generator(llm, self.cache, chunks=yeni, hits=[("c2", 1.0)],
                          corpus_version=bump_version("v1"))
        son = gen2.answer(self.query)
        self.assertEqual(llm.calls, 2, "surum yukseldi ama ESKI cevap donduruldu")
        self.assertEqual(son.citations[0]["span_ids"], ["NEW#7.0"])

    def test_deleted_span_never_appears_in_a_citation(self):
        """ACC-09'un tam şekli: silinmiş sayfaya atıf."""
        eski = {"c1": _Chunk("c1", "silinecek metin", ["OLD#5.0"])}
        llm = _LLM("Cevap [1].")
        _generator(llm, self.cache, chunks=eski, hits=[("c1", 1.0)],
                   corpus_version="v1").answer(self.query)

        kalan = {"c2": _Chunk("c2", "kalan metin", ["KEEP#9.0"])}
        gen = _generator(llm, self.cache, chunks=kalan, hits=[("c2", 1.0)],
                         corpus_version=bump_version("v1"))
        cevap = gen.answer(self.query)
        tum_spanlar = [s for c in cevap.citations for s in c["span_ids"]]
        self.assertNotIn("OLD#5.0", tum_spanlar)

    def test_same_version_still_caches(self):
        """Sürüm değişmediyse cache ÇALIŞMALI; yoksa silme düzeltmesi
        maliyeti üç katına çıkarırdı."""
        chunks = {"c1": _Chunk("c1", "metin", ["A#1.0"])}
        llm = _LLM()
        gen = _generator(llm, self.cache, chunks=chunks, hits=[("c1", 1.0)],
                         corpus_version="v1")
        gen.answer(self.query)
        gen.answer(self.query)
        self.assertEqual(llm.calls, 1)

    def test_bump_always_changes_the_version(self):
        for v in ("", "v1", "3", "abc123def", "2026-09-13"):
            with self.subTest(v=v):
                self.assertNotEqual(bump_version(v), v)


class CascadePropagationTests(unittest.TestCase):
    """Silme ÜÇ indekse birden gitmeli; biri atlanırsa kaynak yarı yaşar."""

    def test_all_indexes_receive_the_delete(self):
        dense, bm25, sparse = _Index(["d1", "d2"]), _Index(["d1"]), _Index(["d1"])
        sonuc = delete_source("d1", dense=dense, bm25=bm25, sparse=sparse,
                              log_path=None)
        self.assertTrue(sonuc.complete)
        for ix in (dense, bm25, sparse):
            self.assertEqual(ix.deleted, ["d1"])
            self.assertNotIn("d1", ix.doc_ids())

    def test_other_sources_are_untouched(self):
        dense = _Index(["d1", "d2"])
        delete_source("d1", dense=dense, log_path=None)
        self.assertEqual(dense.doc_ids(), ["d2"])

    def test_partial_failure_is_reported_not_hidden(self):
        """Yarı silinmiş kaynak, silinmemiş kaynaktan DAHA tehlikelidir:
        sistem 'sildim' der, indeks hâlâ atıf döndürür."""
        class _Bozuk(_Index):
            def delete(self, doc_id):
                raise RuntimeError("qdrant kapali")

        sonuc = delete_source("d1", dense=_Bozuk(["d1"]), bm25=_Index(["d1"]),
                              log_path=None)
        self.assertFalse(sonuc.complete)
        self.assertTrue(sonuc.errors)

    def test_deleting_an_unknown_source_is_not_an_error(self):
        """Yeniden denenen silme (ağ hatası sonrası) patlamamalı."""
        sonuc = delete_source("yok", dense=_Index(["d1"]), log_path=None)
        self.assertTrue(sonuc.complete)

    def test_empty_doc_id_touches_nothing(self):
        """Boş doc_id ile "her şeyi sil" kazası. Sözleşme İSTİSNA ATMAZ,
        `errors` dolu bir sonuç döndürür — ÖNEMLİ OLAN indekslere hiç
        dokunulmamasıdır; bir `delete("")` çağrısı indeks uygulamasına göre
        her şeyi silebilirdi."""
        dense, bm25 = _Index(["d1", "d2"]), _Index(["d1"])
        sonuc = delete_source("", dense=dense, bm25=bm25, log_path=None)
        self.assertFalse(sonuc.complete)
        self.assertTrue(sonuc.errors)
        self.assertEqual(dense.deleted, [], "bos doc_id indekse gecti")
        self.assertEqual(bm25.deleted, [])
        self.assertEqual(dense.doc_ids(), ["d1", "d2"])


class VersionlessCacheTests(unittest.TestCase):
    """Sürümsüz cache = silinmiş kaynağa atıf. Fail-closed olmalı."""

    def test_versionless_cache_is_disabled_and_warns(self):
        chunks = {"c1": _Chunk("c1", "metin", ["A#1.0"])}
        llm = _LLM()
        with warnings.catch_warnings(record=True) as uyarilar:
            warnings.simplefilter("always")
            gen = _generator(llm, ResponseCache(SQLiteCache(":memory:")),
                             chunks=chunks, hits=[("c1", 1.0)], corpus_version="")
            gen.answer("s")
            gen.answer("s")
        self.assertEqual(llm.calls, 2, "surumsuz cache SESSIZCE calisiyor")
        self.assertTrue(uyarilar, "surumsuz cache uyari vermiyor")


if __name__ == "__main__":
    unittest.main()
