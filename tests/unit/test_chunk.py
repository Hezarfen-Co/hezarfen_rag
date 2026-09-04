"""Faz 1.1 birim testleri — chunking (sentetik CanonicalUnit'ler, deterministik)."""
import unittest

from src.ingest.canonical import CanonicalUnit, CanonicalDoc
from src.ingest.pdf_parse import HEADING, PARAGRAPH
from src.chunk import chunk_document, approx_tokens

WORDS40 = " ".join(f"kelime{i}" for i in range(40))   # ~56 approx token


def _u(n, text, kind=PARAGRAPH, page=1, vis="mixed", disi=False):
    return CanonicalUnit(span_id=f"doc#{page}.{n}", doc_id="doc", sinif="12",
                         ders="biyoloji", kaynak_turu="ders_kitabi", page=page,
                         bbox=(0, 0, 100, 20), block_no=n, kind=kind, text=text,
                         page_visual=vis, retrieval_disi=disi)


def _doc(units):
    return CanonicalDoc(source_path="x", doc_id="doc", source_version="v", sinif="12",
                        ders="biyoloji", kaynak_turu="ders_kitabi", page_count=1, units=units)


class TokenTests(unittest.TestCase):
    def test_approx(self):
        self.assertEqual(approx_tokens("a b c d"), round(4 * 1.4))
        self.assertEqual(approx_tokens(""), 0)


class ChunkTests(unittest.TestCase):
    def setUp(self):
        units = [_u(i, WORDS40) for i in range(8)]          # 8 paragraf ~56 tok
        self.doc = _doc(units)
        self.chunks = chunk_document(self.doc)
        self.children = [c for c in self.chunks if c.level == "child"]
        self.parents = [c for c in self.chunks if c.level == "parent"]

    def test_children_created_and_sized(self):
        self.assertGreaterEqual(len(self.children), 2)       # 8×56≈450 tok → ≥2 çocuk
        # her çocuk makul boyutta (tek dev birim yoksa CHILD_MAX civarını çok aşmaz)
        for c in self.children:
            self.assertGreater(c.approx_tokens, 0)

    def test_all_span_ids_preserved(self):
        got = {sid for c in self.children for sid in c.span_ids}
        want = {u.span_id for u in self.doc.units}
        self.assertEqual(got, want)                          # hiçbir birim kaybolmadı

    def test_heading_starts_new_child_when_buffer_full(self):
        # çocuk CHILD_MIN'i (150) geçtikten sonra başlık yeni çocuğu başlatır
        units = [_u(0, WORDS40), _u(1, WORDS40), _u(2, WORDS40),   # ~168 tok
                 _u(3, "1.2 Yeni Bölüm", HEADING), _u(4, WORDS40)]
        chunks = [c for c in chunk_document(_doc(units)) if c.level == "child"]
        heading_chunk = next(c for c in chunks if "doc#1.3" in c.span_ids)
        self.assertNotIn("doc#1.0", heading_chunk.span_ids)   # başlık öncesi ayrı çocukta

    def test_small_heading_does_not_split(self):
        # küçük tampon + başlık → bölmez (minik chunk oluşmaz)
        units = [_u(0, "kısa"), _u(1, "1.2 Yeni Bölüm", HEADING), _u(2, WORDS40)]
        chunks = [c for c in chunk_document(_doc(units)) if c.level == "child"]
        self.assertEqual(len(chunks), 1)                      # hepsi tek çocukta

    def test_parents_link_children(self):
        self.assertGreaterEqual(len(self.parents), 1)
        for p in self.parents:
            self.assertTrue(p.child_ids)
            for cid in p.child_ids:
                child = next(c for c in self.children if c.chunk_id == cid)
                self.assertEqual(child.parent_id, p.chunk_id)

    def test_parent_span_ids_union_of_children(self):
        p = self.parents[0]
        child_spans = {sid for cid in p.child_ids
                       for c in self.children if c.chunk_id == cid for sid in c.span_ids}
        self.assertEqual(set(p.span_ids), child_spans)

    def test_excluded_units_not_chunked(self):
        units = [_u(0, WORDS40), _u(1, "Değerlendirme Soruları " + WORDS40, disi=True)]
        chunks = chunk_document(_doc(units))
        allspans = {sid for c in chunks for sid in c.span_ids}
        self.assertIn("doc#1.0", allspans)
        self.assertNotIn("doc#1.1", allspans)                # sızıntı chunk'a girmez

    def test_metadata_propagated(self):
        c = self.children[0]
        self.assertEqual((c.doc_id, c.sinif, c.ders, c.kaynak_turu),
                         ("doc", "12", "biyoloji", "ders_kitabi"))
        self.assertLessEqual(c.page_start, c.page_end)


if __name__ == "__main__":
    unittest.main()
