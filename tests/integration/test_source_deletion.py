"""#76 (EXP-010/OPS-01 + EVAL-16) — kaynak silme: kaskad ve kanıt.

ÖLÇÜLEN DURUM: indekslerin genel API'si yalnız `build/search/collection/dim`
idi — **`add`/`delete`/`update` YOKTU**. `build()` her çağrıda koleksiyonu
siliyordu (ölçüldü: 10 nokta build → 5 yeni id ile `build()` → koleksiyonda
**5** nokta, 15 değil). Daha temeli: chunk→kaynak eşlemesi (`doc_id`) hiçbir
indekste payload olarak tutulmuyordu → *"şu kaynağın vektörlerini sil"* sorgusu
**teknik olarak ifade edilemiyordu**.

BAŞARISIZLIK: öğretmen ders notunu silerse vektör silinemez → **silinmiş
nottan alıntı yapan cevaplar üretilmeye devam eder**. KVKK silme yükümlülüğü
de imkânsız hâle gelir.

Bu dosya gerçek indekslerle (Qdrant bellek-içi + rank_bm25 + sparse) çalışır.
"""
import json
import os
import tempfile
import unittest

import numpy as np

from src.corpus.deletion import (DeletionResult, bump_version, delete_source,
                                 read_log)
from src.index import BM25Index, DenseIndex
from src.retrieve import SparseIndex


def _vecs(n, seed=0):
    rng = np.random.RandomState(seed)
    v = rng.rand(n, 8).astype("float32")
    return v / np.linalg.norm(v, axis=1, keepdims=True)


class DenseIndexLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.ix = DenseIndex(dim=8)
        self.ix.build([f"a{i}" for i in range(10)], _vecs(10), doc_id="DOC_A")

    def test_upsert_adds_instead_of_wiping(self):
        """Ölçülen hata: `build()` ikinci çağrıda koleksiyonu siliyordu."""
        self.ix.upsert([f"b{i}" for i in range(5)], _vecs(5, 1), doc_id="DOC_B")
        self.assertEqual(len(self.ix), 15)

    def test_build_still_wipes_on_purpose(self):
        """`build` sıfırdan kurar — bu bilinçli; `upsert` eklemek içindir."""
        self.ix.build([f"c{i}" for i in range(3)], _vecs(3, 2), doc_id="DOC_C")
        self.assertEqual(len(self.ix), 3)

    def test_delete_removes_only_that_source(self):
        self.ix.upsert([f"b{i}" for i in range(5)], _vecs(5, 1), doc_id="DOC_B")
        silinen = self.ix.delete("DOC_A")
        self.assertEqual(silinen, 10)
        self.assertEqual(len(self.ix), 5)
        self.assertEqual(self.ix.doc_ids(), {"DOC_B"})

    def test_deleted_source_no_longer_retrievable(self):
        """Asıl ürün sözü: silinen kaynaktan artık ALINTI YAPILAMAZ."""
        self.ix.upsert([f"b{i}" for i in range(5)], _vecs(5, 1), doc_id="DOC_B")
        self.ix.delete("DOC_A")
        bulunan = {cid for cid, _ in self.ix.search(_vecs(1)[0], top_k=20)}
        self.assertFalse({c for c in bulunan if c.startswith("a")},
                         "silinmiş kaynağın chunk'ı hâlâ aramada çıkıyor")

    def test_deleting_unknown_source_is_a_noop(self):
        self.assertEqual(self.ix.delete("YOK"), 0)
        self.assertEqual(len(self.ix), 10)

    def test_upsert_replaces_an_existing_chunk(self):
        self.ix.upsert(["a0"], _vecs(1, 9), doc_id="DOC_A")
        self.assertEqual(len(self.ix), 10, "aynı chunk_id iki kez eklendi")

    def test_source_ids_are_tracked(self):
        self.assertEqual(self.ix.doc_ids(), {"DOC_A"})


class LexicalAndSparseDeletionTests(unittest.TestCase):
    def setUp(self):
        self.bm = BM25Index().build(["a1", "a2"],
                                    ["mitokondri enerji uretir",
                                     "ribozom protein sentezler"], doc_id="A")
        self.bm.add(["b1"], ["kloroplast fotosentez yapar"], doc_id="B")
        self.sp = SparseIndex().build(["a1", "a2"], [{"1": 0.5}, {"2": 0.5}],
                                      doc_id="A")
        self.sp.add(["b1"], [{"3": 0.9}], doc_id="B")

    def test_bm25_delete_removes_the_source(self):
        self.assertEqual(self.bm.delete("A"), 2)
        self.assertEqual(self.bm.doc_ids(), {"B"})

    def test_bm25_search_no_longer_returns_deleted_chunks(self):
        self.bm.delete("A")
        bulunan = {cid for cid, _ in self.bm.search("mitokondri", 10)}
        self.assertNotIn("a1", bulunan)

    def test_bm25_still_finds_the_remaining_source(self):
        """Silme diğer kaynağı bozmamalı — IDF yeniden hesaplanıyor.

        DİKKAT (BM25'in matematiği, silme hatası DEĞİL): tek belge kalınca
        IDF = log((N-n+0.5)/(n+0.5)) → N=n=1 için **negatif** olur ve skorlar
        ≤ 0'a düşer. Bu yüzden test skorun işaretine değil, chunk'ın
        **döndürülmesine** bakar. Üretimde korpus büyük olduğu için sorun
        değil; ama korpus tek kaynağa inerse BM25 sıralaması anlamsızlaşır —
        hibrit füzyonda dense/sparse bunu telafi eder."""
        self.bm.delete("A")
        bulunan = [cid for cid, _ in self.bm.search("fotosentez", 10)]
        self.assertIn("b1", bulunan)
        self.assertNotIn("a1", bulunan)

    def test_sparse_delete(self):
        self.assertEqual(self.sp.delete("A"), 2)
        self.assertEqual(len(self.sp), 1)
        self.assertEqual(self.sp.doc_ids(), {"B"})

    def test_delete_is_idempotent(self):
        self.bm.delete("A")
        self.assertEqual(self.bm.delete("A"), 0)


class CascadeTests(unittest.TestCase):
    """Kaskad tek yerde olmalı — üç indeksten birini unutmak kolay."""

    def setUp(self):
        self.dense = DenseIndex(dim=8)
        self.dense.build(["a1", "a2"], _vecs(2), doc_id="A")
        self.dense.upsert(["b1"], _vecs(1, 5), doc_id="B")
        self.bm = BM25Index().build(["a1", "a2"], ["x y", "z w"], doc_id="A")
        self.bm.add(["b1"], ["q r"], doc_id="B")
        self.sp = SparseIndex().build(["a1", "a2"], [{"1": 1.0}, {"2": 1.0}],
                                      doc_id="A")
        self.sp.add(["b1"], [{"3": 1.0}], doc_id="B")

    def _sil(self, **kw):
        return delete_source("A", dense=self.dense, bm25=self.bm,
                             sparse=self.sp, **kw)

    def test_all_three_indexes_are_cleaned(self):
        r = self._sil(log_path="")
        self.assertEqual((r.dense, r.bm25, r.sparse), (2, 2, 2))
        self.assertEqual(r.total, 6)
        self.assertTrue(r.complete)

    def test_other_source_survives(self):
        self._sil(log_path="")
        self.assertEqual(self.dense.doc_ids(), {"B"})
        self.assertEqual(self.bm.doc_ids(), {"B"})
        self.assertEqual(self.sp.doc_ids(), {"B"})

    def test_cache_is_invalidated_by_version_bump(self):
        """Vektör silinse bile `ResponseCache` TTL boyunca eski cevabı döndürür.
        Tek doğru yol sürümü değiştirmek (#77 ile birlikte çalışır)."""
        r = self._sil(corpus_version="v3", log_path="")
        self.assertTrue(r.cache_invalidated)
        self.assertEqual(r.new_corpus_version, "v4")

    def test_partial_failure_is_not_hidden(self):
        """Sessiz başarı, silinmemiş veriyi silinmiş sanmak demektir."""
        class _Bozuk:
            def delete(self, doc_id):
                raise RuntimeError("qdrant kapali")

        r = delete_source("A", dense=_Bozuk(), bm25=self.bm, sparse=self.sp,
                          log_path="")
        self.assertFalse(r.complete)
        self.assertTrue(any("dense" in e for e in r.errors))
        self.assertEqual(r.bm25, 2, "bir katman patlayınca diğerleri atlandı")

    def test_empty_doc_id_is_refused(self):
        r = delete_source("", log_path="")
        self.assertFalse(r.complete)


class DeletionLogTests(unittest.TestCase):
    """KVKK: "sildim" demek yetmez, gösterilebilmeli."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.yol = os.path.join(self.d, "silme.jsonl")

    def test_event_is_persisted(self):
        dense = DenseIndex(dim=8)
        dense.build(["a1"], _vecs(1), doc_id="A")
        delete_source("A", dense=dense, log_path=self.yol)
        kayitlar = read_log(self.yol)
        self.assertEqual(len(kayitlar), 1)
        self.assertEqual(kayitlar[0]["doc_id"], "A")
        self.assertEqual(kayitlar[0]["dense"], 1)
        self.assertIn("utc", kayitlar[0])

    def test_multiple_deletions_append(self):
        for d in ("A", "B"):
            delete_source(d, log_path=self.yol)
        self.assertEqual(len(read_log(self.yol)), 2)

    def test_log_failure_is_reported_not_swallowed(self):
        r = delete_source("A", log_path="/dev/null/yok/silme.jsonl")
        self.assertFalse(r.complete)
        self.assertTrue(any("izi" in e for e in r.errors))

    def test_logging_off_still_deletes(self):
        dense = DenseIndex(dim=8)
        dense.build(["a1"], _vecs(1), doc_id="A")
        r = delete_source("A", dense=dense, log_path="")
        self.assertEqual(r.dense, 1)
        self.assertTrue(r.complete)


class VersionBumpTests(unittest.TestCase):
    def test_numeric_versions_increment(self):
        self.assertEqual(bump_version("v3"), "v4")
        self.assertEqual(bump_version("v0"), "v1")

    def test_hash_versions_get_a_suffix(self):
        self.assertEqual(bump_version("abc123"), "abc123+1")
        self.assertEqual(bump_version("abc123+1"), "abc123+2")

    def test_empty_version_becomes_timestamped(self):
        v = bump_version("")
        self.assertTrue(v.startswith("v"))
        self.assertTrue(v[1:].isdigit())

    def test_bump_always_changes_the_value(self):
        for v in ("v1", "abc", "abc+9", ""):
            self.assertNotEqual(bump_version(v), v)


if __name__ == "__main__":
    unittest.main()
