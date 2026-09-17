"""Kiracılık (çok-okul) — okul İSTEKLE taşınır, store okulla kapsamlanır.

ÖLÇÜLEN DURUM (2026-09-17 öncesi): korpus anahtarı yalnız `(sınıf, ders)`ti.
İki okulun aynı (sınıf, ders) korpusu TEK anahtara düşüyor, ikincisi birincisini
EZLİYORDU; depoda okul boyutu HİÇ yoktu (`meta {sinif, ders}`, payload
`{chunk_id, doc_id}`). Yani okul A'nın isteği, okul B'nin içeriğinden ayırt
edilemiyordu — bu dosya o ayrımı üç katmanda kilitler: store, kayıt defteri,
hab/2 çerçevesi (okul EKO'su).

KURAL: okulla kapsanmış ya da hiç. Damgasız (eski) satır taşınmaz ve HİÇBİR
okura görünmez; okulsuz okur hiçbir satır görmez.

Hermetik: ağ/model yok (küçük sentetik vektörler + sahte servisler).
"""
import os
import tempfile
import unittest

import numpy as np

from src.bridge.contract import (AI_CHAT_CAPABILITY, AI_RAG_CHAT_CAPABILITY,
                                 AI_RAG_INDEX_CAPABILITY, BridgeFrameError,
                                 BridgeRequest)
from src.bridge.dispatch import Dispatcher, INDEX_UNWIRED
from src.cache.response_cache import canonical_key
from src.guard.tenant import (TenantError, content_visible, normalize_school,
                              require_owner, visible_owners)
from src.index import BM25Index, DenseIndex
from src.retrieve import HybridRetriever
from src.service.multi import (MultiCorpusService, discover_tenants,
                               school_from_book_path, spec_label)
from src.service.registry import CorpusKey, CorpusRegistry

A, B = "okul-a", "okul-b"


class TenantValueTests(unittest.TestCase):
    def test_school_is_validated(self):
        self.assertEqual(normalize_school(A), A)
        self.assertIsNone(normalize_school(None))
        self.assertIsNone(normalize_school("  "))
        for kotu in ("Okul A", "okul a!", "__public__", "-okul"):
            with self.assertRaises(TenantError):
                normalize_school(kotu)          # biçim/ayrılmış değer: reddedilir

    def test_write_owner_is_mandatory(self):
        self.assertEqual(require_owner(A), A)
        for bos in (None, "", "   ", "Okul A"):
            with self.assertRaises(TenantError):
                require_owner(bos)              # sahipsiz yazma yok

    def test_visibility_is_exact_match(self):
        self.assertEqual(visible_owners(A), frozenset({A}))
        self.assertEqual(visible_owners(None), frozenset())
        self.assertTrue(content_visible(A, A))
        self.assertFalse(content_visible(B, A))     # yabancı okul GÖRÜNMEZ
        self.assertFalse(content_visible(A, None))  # okulsuz okur: hiçbir satır yok
        self.assertFalse(content_visible(None, A))  # damgasız satır: erişilemez


class StoreScopeTests(unittest.TestCase):
    """Aynı koleksiyonda iki okulun satırları: okur yalnız kendi okulunu görür."""

    def test_dense_search_is_scoped_by_reader_school(self):
        idx = DenseIndex(dim=4).build(["a1"], np.eye(4, dtype=np.float32)[:1],
                                      school=A)
        idx.upsert(["b1"], np.eye(4, dtype=np.float32)[1:2], school=B)
        v = np.eye(4, dtype=np.float32)[0]
        self.assertEqual([c for c, _ in idx.search(v, 5, school=A)], ["a1"])
        self.assertEqual([c for c, _ in idx.search(v, 5, school=B)], ["b1"])
        self.assertEqual(idx.search(v, 5, school=None), [])   # okulsuz → hiç

    def test_index_writes_require_a_real_owner(self):
        with self.assertRaises(TenantError):
            DenseIndex(dim=4).build(["x"], np.eye(4, dtype=np.float32)[:1], school=None)
        with self.assertRaises(TenantError):
            BM25Index().build(["x"], ["metin"], school="")
        with self.assertRaises(TenantError):
            BM25Index().build(["x"], ["metin"], school="Okul A")


class RegistryTenantTests(unittest.TestCase):
    class _Doc:
        def __init__(self, sinif, ders):
            self.sinif, self.ders = sinif, ders

    class _Svc:
        def __init__(self, school, sinif, ders):
            self.school = school
            self.doc = RegistryTenantTests._Doc(sinif, ders)
            self.ders = ders
            self.generator = type("G", (), {"chunks_by_id": {}})()

    def _iki_okul(self):
        r = CorpusRegistry()
        ra = r.register(self._Svc(A, "10", "biyoloji"))
        rb = r.register(self._Svc(B, "10", "biyoloji"))
        return r, ra, rb

    def test_two_schools_coexist_where_the_old_key_collapsed_them(self):
        r, ra, rb = self._iki_okul()
        self.assertEqual(len(r), 2)
        self.assertNotEqual(ra, rb)
        self.assertEqual(str(ra), f"{A}/10/biyoloji")
        self.assertEqual(str(rb), f"{B}/10/biyoloji")

    def test_resolve_only_returns_the_readers_own_corpus(self):
        r, _, _ = self._iki_okul()
        svc, _ = r.resolve({"school": A, "scope": [{"sinif": "10", "ders": "biyoloji"}]})
        svc_b, _ = r.resolve({"school": B,
                              "scope": [{"sinif": "10", "ders": "biyoloji"}]})
        self.assertIs(svc, r.get("10", "biyoloji", school=A))
        self.assertIs(svc_b, r.get("10", "biyoloji", school=B))
        self.assertIsNot(svc, svc_b)

    def test_school_less_request_is_a_typed_refusal(self):
        r, _, _ = self._iki_okul()
        svc, sebep = r.resolve({"scope": [{"sinif": "10", "ders": "biyoloji"}]})
        self.assertIsNone(svc)
        self.assertEqual(sebep, "school_required")
        self.assertIsNone(r.get("10", "biyoloji"))     # okulsuz okur: korpus yok

    def test_invalid_school_is_a_typed_refusal(self):
        r, _, _ = self._iki_okul()
        for kotu in ("Okul A", "okul a!", "-x"):
            svc, sebep = r.resolve({"school": kotu,
                                    "scope": [{"sinif": "10", "ders": "biyoloji"}]})
            self.assertIsNone(svc)
            self.assertEqual(sebep, "unknown_school", kotu)

    def test_registration_without_any_school_is_refused(self):
        class _Bos:
            doc = type("D", (), {"sinif": "10", "ders": "biyoloji"})()
            ders = "biyoloji"
        with self.assertRaises(ValueError):
            CorpusRegistry().register(_Bos())


class _Emb:
    """Sentetik gömücü: metin → sabit vektör (ağ/model yok)."""

    def embed(self, texts):
        return np.ones((len(list(texts)), 4), dtype=np.float32)

    def embed_sparse(self, texts):
        return [{"1": 1.0} for _ in list(texts)]


class RetrieverTenantTests(unittest.TestCase):
    """Store süzgeci + meta damgası birlikte: B'nin chunk'ı A'ya asla gelmez."""

    def _retr(self, ids, texts, meta, write_school):
        return HybridRetriever(
            _Emb(),
            DenseIndex(dim=4).build(ids, np.ones((len(ids), 4), dtype=np.float32),
                                    school=write_school),
            BM25Index().build(ids, texts, school=write_school),
            meta=meta)

    def test_school_a_never_retrieves_school_bs_chunk(self):
        meta = {"b1": {"sinif": "10", "ders": "biyoloji", "school": B}}
        r = self._retr(["b1"], ["gizli okul b notu"], meta, B)
        self.assertEqual(r.retrieve("gizli", top_k=5, school=A), [])
        self.assertEqual(r.retrieve("gizli", top_k=5), [])       # okulsuz okur
        self.assertEqual([c for c, _ in r.retrieve("gizli", top_k=5, school=B)], ["b1"])

    def test_untagged_rows_are_unreachable(self):
        """Damgasız satır bir okula atfedilemez: taşınmaz, erişilemez."""
        meta = {"x1": {"sinif": "10", "ders": "biyoloji"}}       # okul damgası yok
        r = self._retr(["x1"], ["damgasız"], meta, A)
        self.assertEqual(r.retrieve("damgasız", top_k=5, school=A), [])

    def test_meta_school_must_match_the_reader(self):
        meta = {"a1": {"sinif": "10", "ders": "biyoloji", "school": A}}
        r = self._retr(["a1"], ["okul a notu"], meta, A)
        self.assertEqual([c for c, _ in r.retrieve("okul", top_k=5, school=A)], ["a1"])
        self.assertEqual(r.retrieve("okul", top_k=5, school=B), [])


class CacheTenantTests(unittest.TestCase):
    def test_cache_key_separates_schools(self):
        ortak = dict(query="DNA nedir?", role="student", ders="biyoloji",
                     corpus_version="v1")
        self.assertNotEqual(canonical_key(school=A, **ortak),
                            canonical_key(school=B, **ortak))
        self.assertNotEqual(canonical_key(school=A, **ortak),
                            canonical_key(school="", **ortak))


class MultiCorpusTenantTests(unittest.TestCase):
    class _Fake:
        def __init__(self, school, sinif, ders):
            self.school = school
            self.doc = type("D", (), {"sinif": sinif, "ders": ders})()
            self.ders = ders
            self.generator = type("G", (), {"chunks_by_id": {"c1": 1}})()

        def chat(self, req):
            return {"text": f"{self.school}:{self.doc.sinif}/{self.ders}",
                    "abstained": False, "reason": "", "citations": [],
                    "used_source_ids": [], "cost_usd": 0.0, "cache_hit": False}

    def _svc(self, specs, *, school=None):
        s = MultiCorpusService(
            specs, school=school, shared=object(),
            builder=lambda yol, *, sinif, ders, school, shared=None, **kw:
                self._Fake(school, sinif, ders))
        s._specs = {k: __file__ for k in s._specs}     # yol kontrolünü aş
        return s

    def test_same_subject_two_schools_are_two_corpora(self):
        s = self._svc([(A, "10", "biyoloji"), (B, "10", "biyoloji")])
        self.assertEqual(len(s.known()), 2)
        s.warm()
        a = s.chat({"query": "s", "school": A,
                    "scope": [{"sinif": "10", "ders": "biyoloji"}]})
        b = s.chat({"query": "s", "school": B,
                    "scope": [{"sinif": "10", "ders": "biyoloji"}]})
        self.assertEqual(a["text"], f"{A}:10/biyoloji")
        self.assertEqual(b["text"], f"{B}:10/biyoloji")

    def test_subject_specs_expand_for_the_configured_school(self):
        s = self._svc(["10/biyoloji", "10/kimya"], school=A)
        self.assertEqual(s.known(), [(A, "10", "biyoloji"), (A, "10", "kimya")])

    def test_subject_specs_without_a_school_are_refused(self):
        with self.assertRaises(ValueError):
            MultiCorpusService(["10/biyoloji"], shared=object(),
                               builder=lambda *a, **k: None)

    def test_school_less_request_is_refused(self):
        s = self._svc([(A, "10", "biyoloji")])
        out = s.chat({"query": "s", "role": {"role": "student", "sinif": "10",
                                             "ders_list": ["biyoloji"]}})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "school_required")

    def test_other_school_cannot_reach_this_corpus(self):
        s = self._svc([(A, "10", "biyoloji")])
        out = s.chat({"query": "s", "school": B,
                      "scope": [{"sinif": "10", "ders": "biyoloji"}]})
        self.assertTrue(out["abstained"])
        self.assertEqual(out["reason"], "no_corpus")

    def test_invalid_school_is_refused_with_a_typed_reason(self):
        s = self._svc([(A, "10", "biyoloji")])
        out = s.chat({"query": "s", "school": "Okul A",
                      "scope": [{"sinif": "10", "ders": "biyoloji"}]})
        self.assertEqual(out["reason"], "unknown_school")

    def test_spec_labels_always_show_the_school(self):
        self.assertEqual(spec_label((A, "10", "biyoloji")), f"{A}/10/biyoloji")
        self.assertEqual(spec_label("10/biyoloji", school=A), f"{A}/10/biyoloji")

    def test_discovery_finds_school_corpora_on_disk(self):
        with tempfile.TemporaryDirectory() as kok:
            for okul in (A, B):
                os.makedirs(os.path.join(kok, okul, "lise", "10", "biyoloji"))
                open(os.path.join(kok, okul, "lise", "10", "biyoloji",
                                  "kitap.pdf"), "w").close()
            self.assertEqual(discover_tenants(root=kok),
                             [(A, "10", "biyoloji"), (B, "10", "biyoloji")])
            self.assertEqual(discover_tenants(root=kok,
                                              subjects=[("10", "kimya")]), [])

    def test_owner_is_read_from_the_book_path_layout(self):
        self.assertEqual(
            school_from_book_path("/app/data/okul-a/lise/10/biyoloji/kitap.pdf",
                                  root="/app/data"), A)
        with self.assertRaises(ValueError):      # okulsuz düzen artık geçersiz
            school_from_book_path("/app/data/lise/10/biyoloji/kitap.pdf",
                                  root="/app/data")


class BridgeEchoTests(unittest.TestCase):
    """hab/2: okul çerçevede ZORUNLU, cevapta AYNEN eko edilir."""

    class _Svc:
        def __init__(self):
            self.seen = []

        def chat(self, req):
            self.seen.append(req)
            return {"text": "cevap", "abstained": False, "reason": "",
                    "citations": [{"n": 1, "doc_id": "abc123", "pages": [20],
                                   "span_ids": ["abc123#20.1"], "ders": "biyoloji",
                                   "chunk_id": "abc123:c1"}],
                    "used_source_ids": [], "cost_usd": 0.0, "cache_hit": False}

    def _cerceve(self, **kw):
        d = {"id": "01T", "school": A, "capability": AI_RAG_CHAT_CAPABILITY,
             "deadline_ms": 5000,
             "payload": {"message": "DNA nedir?", "asker": "01U",
                         "asker_role": "student",
                         "scope": [{"sinif": "10", "ders": "biyoloji"}],
                         "history": []}}
        d.update(kw)
        return d

    def test_frame_without_school_is_malformed(self):
        with self.assertRaises(BridgeFrameError):
            BridgeRequest.from_wire({"id": "01T", "capability": AI_CHAT_CAPABILITY})
        self.assertIsNone(Dispatcher(self._Svc()).handle(
            {"id": "01T", "capability": AI_CHAT_CAPABILITY}))

    def test_school_is_echoed_and_reaches_the_service_body(self):
        svc = self._Svc()
        out = Dispatcher(svc).handle(self._cerceve())
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["school"], A)                 # EKO
        self.assertEqual(svc.seen[0]["school"], A)         # servis gövdesine geçti
        self.assertEqual(svc.seen[0]["role"], {"role": "student"})
        self.assertEqual(svc.seen[0]["user"], "01U")
        self.assertEqual(out["payload"]["citations"][0]["doc_id"], "abc123")

    def test_invalid_school_is_refused_and_still_echoed(self):
        out = Dispatcher(self._Svc()).handle(self._cerceve(school="Okul A"))
        self.assertEqual(out["status"], "err")
        self.assertEqual(out["code"], "invalid_school")
        self.assertEqual(out["school"], "Okul A")

    def test_rag_index_is_refused_until_the_transport_exists(self):
        out = Dispatcher(self._Svc()).handle(self._cerceve(
            capability=AI_RAG_INDEX_CAPABILITY, payload={}))
        self.assertEqual(out["status"], "err")
        self.assertEqual(out["code"], INDEX_UNWIRED)
        self.assertEqual(out["school"], A)

    def test_unknown_capability_is_refused(self):
        out = Dispatcher(self._Svc()).handle(self._cerceve(capability="rag.nope"))
        self.assertEqual(out["code"], "unsupported_capability")

    def test_chat_reply_carries_text_only(self):
        out = Dispatcher(self._Svc()).handle(self._cerceve(
            capability=AI_CHAT_CAPABILITY,
            payload={"message": "merhaba", "asker_role": "student",
                     "history": [{"role": "user", "content": "önce"}]}))
        self.assertEqual(out["payload"], {"text": "cevap"})
        self.assertEqual(out["school"], A)


class CorpusKeyRenderingTests(unittest.TestCase):
    def test_key_always_names_its_school(self):
        self.assertEqual(str(CorpusKey(A, "10", "biyoloji")), f"{A}/10/biyoloji")


if __name__ == "__main__":
    unittest.main()
