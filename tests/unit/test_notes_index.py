"""`rag.index` dizinleme yolu — çevrimdışı (ağ YOK, model YOK).

Sahte gömme sağlayıcısı SABİT (hash tohumlu) vektörler üretir; sahte blob
okuyucu baytları yerel sözlükten verir. Testin ölçtüğü iddialar:

  1. notun KENDİ başlık+içeriği ek olmadan da indekslenir;
  2. ekler okunur, `files[].id` AYNEN yankılanır (`doc_id` içerik sha256'sıdır);
  3. yeniden indeksleme ÇOĞALTMAZ (notun satırları değiştirilir);
  4. okunamayan bir ek dizinlemeyi DURDURMAZ ve cevapta adı geçer;
  5. not kanalı okul süzgeciyle aranır (başka okulun satırı görünmez).
"""
from __future__ import annotations

import hashlib
import unittest

import numpy as np

from src.bridge.contract import BlobReadRefused, RagIndexPayload, RagFile
from src.index.notes import NoteIndex, doc_id_for_bytes
from src.service.notes_index import index_course_note


class SahteEmbedder:
    """Deterministik, ağsız gömme. Dense: tohumlu rastgele 1024 boyut."""

    def _vec(self, text: str) -> np.ndarray:
        tohum = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        return np.random.default_rng(tohum).random(1024).astype(np.float32)

    def embed(self, texts, batch_size=None):
        return [self._vec(t) for t in texts]

    def embed_query(self, query):
        return [self._vec(query)]

    def embed_sparse(self, texts):
        return [{w: 1.0 for w in t.lower().split()} for t in texts]

    def embed_both(self, texts, batch_size=16):
        return self.embed(texts), self.embed_sparse(texts)


class SahteBlobOkuyucu:
    def __init__(self, blobs, *, refuse=()):
        self.blobs = blobs
        self.refuse = set(refuse)
        self.istekler: list[dict] = []

    def read(self, request, *, max_bytes):
        self.istekler.append(dict(request))
        fid = str(request["file"])
        if fid in self.refuse:
            raise BlobReadRefused("forbidden", "bu dosyayı göremiyorsun")
        name, content_type, data = self.blobs[fid]
        return ({"status": "ok", "name": name, "content_type": content_type,
                 "size": len(data)}, data)


def _payload(**ustune) -> RagIndexPayload:
    alanlar = dict(course_note="01NOTE", course="01COURSE", author="01AUTHOR",
                   title="Hücre ve Canlıların Ortak Özellikleri",
                   content="Hücre, canlıların en küçük yapı ve görev birimidir.",
                   files=[])
    alanlar.update(ustune)
    return RagIndexPayload(**alanlar)


class NotIndekslemeTestleri(unittest.TestCase):
    def setUp(self) -> None:
        self.index = NoteIndex()
        self.embedder = SahteEmbedder()

    def _indeksle(self, payload=None, reader=None):
        return index_course_note(payload or _payload(), school="okul-a",
                                 blob_reader=reader, note_index=self.index,
                                 embedder=self.embedder)

    def test_ek_olmadan_da_notun_kendi_metni_indekslenir(self):
        """Şart: başlık + içerik HER durumda indekslenir (ek yoksa bile)."""
        cevap = self._indeksle()
        self.assertEqual(cevap["course_note"], "01NOTE")
        self.assertGreater(cevap["chunks"], 0)
        self.assertEqual(cevap["files"], [])
        # Özet insan içindir: notun başlığını anar (Türkçe, 1-2 cümle).
        self.assertIn("Hücre ve Canlıların Ortak Özellikleri", cevap["summary"])
        # Satırlar okul damgasıyla yazıldı (kiracılık).
        self.assertEqual(self.index.stats(), {"okul-a": cevap["chunks"]})

    def test_ek_baytlari_okunur_ve_idler_aynen_yankilanir(self):
        """`files[].id` isteğin verdiği id OLMALI; `doc_id` içerik sha256'sı."""
        data = "Hücre zarı, sitoplazma ve çekirdek.".encode("utf-8")
        reader = SahteBlobOkuyucu({"01FILE": ("ozet.txt", "text/plain", data)})
        cevap = self._indeksle(
            _payload(files=[RagFile(id="01FILE", name="ozet.txt",
                                    content_type="text/plain", size=len(data))]),
            reader)
        self.assertEqual(cevap["files"], [{"id": "01FILE",
                                          "doc_id": doc_id_for_bytes(data),
                                          "name": "ozet.txt"}])
        self.assertEqual(cevap["failed"], [])
        # İstek ADINA OKUMA taşır: `ai` görevlisi hiçbir dersi göremez.
        self.assertEqual(reader.istekler[0]["on_behalf_of"], "01AUTHOR")
        self.assertEqual(reader.istekler[0]["school"], "okul-a")

    def test_yeniden_indeksleme_cogaltmaz(self):
        """Aynı not iki kez indekslenirse satır sayısı İKİYE KATLANMAZ."""
        self._indeksle()
        ilk = self.index.stats()["okul-a"]
        self._indeksle()
        ikinci = self.index.stats()["okul-a"]
        self.assertGreater(ilk, 0)
        self.assertEqual(ikinci, ilk)

    def test_okunamayan_ek_dizinlemeyi_durdurmaz(self):
        """Reddedilen ek atlanır; notun kendi metni indekslenir ve adı geçer."""
        reader = SahteBlobOkuyucu({}, refuse={"01YOK"})
        cevap = self._indeksle(
            _payload(files=[RagFile(id="01YOK", name="yok.pdf",
                                    content_type="application/pdf", size=10)]),
            reader)
        self.assertGreater(cevap["chunks"], 0)
        self.assertEqual(cevap["files"], [])
        self.assertEqual(cevap["failed"][0]["id"], "01YOK")
        self.assertEqual(cevap["failed"][0]["code"], "forbidden")
        self.assertIn("yok.pdf", cevap["summary"])

    def test_blob_okuyucusu_yoksa_not_yine_indekslenir(self):
        """Taşıma blob okuyucusunu takmamışsa (ör. yalın test) ekler düşer,
        notun metni DÜŞMEZ."""
        cevap = self._indeksle(
            _payload(files=[RagFile(id="01FILE", name="a.txt",
                                    content_type="text/plain", size=3)]),
            None)
        self.assertGreater(cevap["chunks"], 0)
        self.assertEqual(cevap["failed"][0]["code"], "blob_unavailable")

    def test_not_kanali_okulla_suzulur(self):
        """Arama okul süzgeçlidir: başka okul bu notu GÖRMEZ."""
        data = "Fotosentez, klorofil ile ışık enerjisini bağlar.".encode("utf-8")
        reader = SahteBlobOkuyucu({"01FILE": ("foto.txt", "text/plain", data)})
        self._indeksle(
            _payload(files=[RagFile(id="01FILE", name="foto.txt",
                                    content_type="text/plain", size=len(data))]),
            reader)
        bulunan = self.index.retrieve("fotosentez klorofil", self.embedder,
                                      school="okul-a")
        self.assertTrue(bulunan, "not kanalı kendi okulunda bulunmalı")
        parcalar = [self.index.chunk(cid) for cid, _ in bulunan]
        ekli = [c for c in parcalar if "klorofil" in c.text]
        self.assertTrue(ekli, "ekin metni kanalda bulunmalı")
        # Ekin parçası içerik sha256'sını doc_id olarak taşır (atıf eşleşmesi).
        self.assertEqual(ekli[0].doc_id, doc_id_for_bytes(data))
        # Başka okul: damgasız/başka okulun satırı ASLA dönmez.
        self.assertEqual(
            self.index.retrieve("fotosentez", self.embedder, school="okul-b"), [])


class BoruHattiUyumTestleri(unittest.TestCase):
    """`NoteAwareChunks`, GERÇEK tüketicisiyle (`rerank_select`) uyumlu olmalı:
    not satırları korpus kurulduktan SONRA gelir, yani `chunks_by_id`/`span_meta`
    sarmalayıcıdan geçer. Sarmalayıcı `Mapping` sözleşmesini bozarsa seçim
    adımı not parçalarını sessizce düşürür."""

    class SahteReranker:
        def rerank(self, query, candidates):
            return [(cid, 0.9) for cid, _ in candidates]

    def test_not_parcasi_secim_adimindan_gecer(self):
        from src.index.notes import NoteAwareChunks
        from src.rerank.pipeline import rerank_select
        index = NoteIndex()
        cevap = index_course_note(
            _payload(), school="okul-a", blob_reader=None, note_index=index,
            embedder=SahteEmbedder())
        self.assertGreater(cevap["chunks"], 0)
        cid = index.retrieve("hücre canlılar", SahteEmbedder(),
                             school="okul-a")[0][0]
        sarmal = NoteAwareChunks({}, index.chunk)
        self.assertIn(cid, sarmal)
        secilen = rerank_select("hücre", [(cid, 1.0)], sarmal,
                                self.SahteReranker(), top_n=1)
        self.assertEqual([c.chunk_id for c in secilen], [cid])
        self.assertIn("Hücre", secilen[0].text)
        self.assertEqual(secilen[0].doc_id, "01NOTE")
        # Span meta da canlı indeksten çözülür (atıf → sayfa).
        self.assertEqual(index.span(index.chunk(cid).span_ids[0])["page"], 1)
        self.assertNotIn("yok", sarmal)


class BasarisizTasimaTestleri(unittest.TestCase):
    def test_sozlesme_disli_tur_indekslenemez_ama_raporlanir(self):
        index = NoteIndex()
        reader = SahteBlobOkuyucu({"01FILE": ("ses.mp3", "audio/mpeg", b"\x00\x01")})
        cevap = index_course_note(
            _payload(files=[RagFile(id="01FILE", name="ses.mp3",
                                    content_type="audio/mpeg", size=2)]),
            school="okul-a", blob_reader=reader, note_index=index,
            embedder=SahteEmbedder())
        self.assertEqual(cevap["failed"][0]["code"], "unsupported_type")
        self.assertEqual(cevap["files"], [])


if __name__ == "__main__":
    unittest.main()
