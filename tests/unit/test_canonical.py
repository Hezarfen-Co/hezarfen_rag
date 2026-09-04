"""Faz 0.5 birim testleri — kanonik birim üretimi (sentetik, deterministik)."""
import unittest

from src.ingest.pdf_parse import Block, Page, ParsedDoc, HEADING, PARAGRAPH, HEADER, LABEL
from src.ingest.canonical import make_span_id, units_from_parsed


def _b(text, block_no, kind=PARAGRAPH, retrieval_disi=False, page=1):
    return Block(page=page, bbox=(10, 20, 300, 40), text=text, block_no=block_no,
                 kind=kind, retrieval_disi=retrieval_disi)


class SpanIdTests(unittest.TestCase):
    def test_format(self):
        self.assertEqual(make_span_id("abc123def456", 12, 3), "abc123def456#12.3")


class UnitsFromParsedTests(unittest.TestCase):
    def setUp(self):
        p = Page(number=1, width=400, height=560, blocks=[
            _b("1.2 Başlık", 0, HEADING),
            _b("DNA çift sarmaldır ve mü\xadhendislik ile değiştirilir.", 1, PARAGRAPH),
            _b("2. BÖLÜM", 2, HEADER),                       # header → hariç
            _b("3,4 nm", 3, LABEL),                           # label → hariç
            _b("Ünite Değerlendirme Soruları", 4, PARAGRAPH, retrieval_disi=True),  # sızıntı
        ])
        self.doc = ParsedDoc(source_path="x.pdf", page_count=1, pages=[p])
        self.units = units_from_parsed(
            self.doc, doc_id="d0c1d2e3f4a5", sinif="12", ders="biyoloji",
            kaynak_turu="ders_kitabi", page_visual={1: "mixed"})

    def test_only_body_units(self):
        # header ve label hariç → 3 birim (heading + paragraph + değerlendirme)
        kinds = [u.kind for u in self.units]
        self.assertEqual(len(self.units), 3)
        self.assertNotIn(HEADER, kinds)
        self.assertNotIn(LABEL, kinds)

    def test_text_normalized(self):
        para = next(u for u in self.units if u.block_no == 1)
        self.assertIn("mühendislik", para.text)      # \xad hece birleşti
        self.assertNotIn("\xad", para.text)

    def test_span_id_and_metadata(self):
        para = next(u for u in self.units if u.block_no == 1)
        self.assertEqual(para.span_id, "d0c1d2e3f4a5#1.1")
        self.assertEqual((para.sinif, para.ders, para.kaynak_turu), ("12", "biyoloji", "ders_kitabi"))
        self.assertEqual(para.page_visual, "mixed")

    def test_retrieval_disi_carried(self):
        excl = next(u for u in self.units if u.block_no == 4)
        self.assertTrue(excl.retrieval_disi)
        self.assertFalse(excl.retrievable)
        # sızan birim retrievable listesinde olmamalı
        self.assertNotIn(excl, [u for u in self.units if u.retrievable])

    def test_retrievable_subset(self):
        self.assertEqual(sum(u.retrievable for u in self.units), 2)  # heading + paragraph


if __name__ == "__main__":
    unittest.main()
