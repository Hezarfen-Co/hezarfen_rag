"""Faz 1.1 integration testi — 12-bio kanonik doküman üzerinde chunking (gerçek veri)."""
import os
import unittest

from src.ingest.canonical import build_canonical
from src.chunk import chunk_document

BOOK = os.path.join("data", "lise", "12", "biyoloji", "kitap.pdf")


@unittest.skipUnless(os.path.exists(BOOK), f"veri yok: {BOOK}")
class Chunk12BioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = build_canonical(BOOK, sinif="12", ders="biyoloji")
        cls.chunks = chunk_document(cls.doc)
        cls.children = [c for c in cls.chunks if c.level == "child"]
        cls.parents = [c for c in cls.chunks if c.level == "parent"]

    def test_children_and_parents_produced(self):
        self.assertGreater(len(self.children), 20)
        self.assertGreater(len(self.parents), 5)

    def test_child_span_ids_exist_in_doc(self):
        doc_spans = {u.span_id for u in self.doc.units}
        child_spans = {sid for c in self.children for sid in c.span_ids}
        self.assertTrue(child_spans.issubset(doc_spans))
        # tüm retrievable birimler bir çocukta yer almalı
        self.assertEqual(child_spans, {u.span_id for u in self.doc.retrievable_units})

    def test_children_linked_to_real_parents(self):
        pids = {p.chunk_id for p in self.parents}
        linked = [c for c in self.children if c.parent_id]
        self.assertGreater(len(linked), 0)
        for c in linked:
            self.assertIn(c.parent_id, pids)

    def test_child_token_sizes_reasonable(self):
        # çoğu çocuk üst sınırın çok üstünde olmamalı (tek dev birim istisnası olabilir)
        big = [c for c in self.children if c.approx_tokens > 600]
        self.assertLess(len(big), len(self.children) * 0.1)

    def test_chunks_have_provenance_and_meta(self):
        for c in self.chunks[:100]:
            self.assertTrue(c.span_ids)
            self.assertTrue(c.text.strip())
            self.assertEqual((c.sinif, c.ders), ("12", "biyoloji"))
            self.assertIn(c.page_visual, {"figure_heavy", "mixed", "low_visual"})


if __name__ == "__main__":
    unittest.main()
