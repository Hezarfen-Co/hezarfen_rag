"""Golden set ÜRETİCİSİNİN kendi kusurları (#65-#71).

Buradaki her test, ölçümde YANLIŞ SONUÇ ÜRETMİŞ gerçek bir kusuru kayda
geçirir. Bozuk bir ölçüm aracı bozuk bir üründen daha tehlikelidir: ürün
doğru davranırken "başarısız" raporu verir ve yanlış yeri düzeltmeye
çalışırsın.

ÖLÇÜLEN: `global` senaryosu recall@5 = **0,034**. Üç ayrı üretici kusuru
vardı; düzeltildikten sonra aynı üründe **0,659** ölçüldü. Ürün kodunda tek
satır değişmedi.
"""
import unittest

from src.eval.golden_build import _baslik_konu_mu, _sade_baslik


class SadeBaslikTests(unittest.TestCase):
    """PDF'in başlık katmanı ham hâliyle soruya konamaz."""

    def test_satir_tekrari_temizlenir(self):
        # PyMuPDF gölgeli başlıkları iki kez döndürüyor.
        self.assertEqual(_sade_baslik("10. Sınıf\n10. Sınıf"), "10. Sınıf")

    def test_sozcuk_tekrari_temizlenir(self):
        self.assertEqual(_sade_baslik("1.\n1.\nTEMA\nTEMA"), "1. TEMA")

    def test_satir_sonu_baslik_icinde_kalmaz(self):
        # "SEMBOLLERİN\nAÇIKLAMASI" soruya gömülünce iki satıra bölünüyordu.
        self.assertEqual(_sade_baslik("SEMBOLLERİN\nAÇIKLAMASI"),
                         "SEMBOLLERİN AÇIKLAMASI")

    def test_bos_girdi_cokmez(self):
        for x in ("", None, "   ", "\n\n"):
            self.assertEqual(_sade_baslik(x), "")


class BaslikKonuMuTests(unittest.TestCase):
    """Başlık katmanında konu adı OLMAYAN şeyler de var."""

    def test_gercek_konu_kabul_edilir(self):
        for ad in ("Krebs (Sitrik Asit) Döngüsü", "Azot Döngüsü",
                   "Mide ve Bağırsak Adaptasyonları",
                   "IŞIK ENERJİSİ KULLANILARAK BESİN SENTEZİ (FOTOSENTEZ)"):
            with self.subTest(ad=ad):
                self.assertTrue(_baslik_konu_mu(ad))

    def test_kimyasal_denklem_reddedilir(self):
        # "6CO2 + 12H2O Işık C6H12O6 + 6O2 + 6H2O konusunu anlatır mısın?"
        # diye bir öğrenci sorusu yoktur.
        for ad in ("6CO2 + 12H2O Işık C6H12O6 + 6O2 + 6H2O",
                   "Glikoz 2 Laktik asit + 2 ATP",
                   "C6H12O6 + 6O2 → 6CO2 + 6H2O"):
            with self.subTest(ad=ad):
                self.assertFalse(_baslik_konu_mu(ad))

    def test_sekil_etiketi_reddedilir(self):
        # Şekil içindeki harf dizileri de "heading" olarak geliyor.
        self.assertFalse(_baslik_konu_mu("P P P Pi P P"))

    def test_cumle_baslik_degildir(self):
        self.assertFalse(_baslik_konu_mu(
            "Suyun fotolizi ile oluşan hidrojenler NADP+ tarafından tutulur."))

    def test_soru_cumlesi_reddedilir(self):
        self.assertFalse(_baslik_konu_mu("Bitkilerin kütlesi nasıl artar? B"))


class GlobalItemTests(unittest.TestCase):
    """Üretilmiş setin `global` item'ları için değişmezler.

    Bunlar dosyanın kendisini denetler: üretici bozulursa set bozulur ve
    ölçüm sessizce yanlışa kayar.
    """

    @classmethod
    def setUpClass(cls):
        import json
        import os
        yol = os.path.join("tests", "golden", "golden_10biy_v2.json")
        if not os.path.isfile(yol):
            raise unittest.SkipTest("golden set uretilmemis")
        veri = json.load(open(yol, encoding="utf-8"))
        cls.global_items = [i for i in veri["items"] if i["senaryo"] == "global"]

    def test_set_bos_degil(self):
        self.assertGreaterEqual(len(self.global_items), 10)

    def test_soru_tek_satirdir(self):
        for i in self.global_items:
            self.assertNotIn("\n", i["soru"], i["id"])

    def test_sayfa_araligi_sorusu_yok(self):
        """"40-52. sayfaları özetle" retrieval sorusu değil, `/rag/summarize`
        kapsam girdisidir. Ölçümde recall@5 = 0,034 çıkmasının nedeniydi."""
        import re
        for i in self.global_items:
            self.assertIsNone(re.search(r"\d+\s*-\s*\d+\.\s*sayfa", i["soru"]),
                              i["soru"])

    def test_gold_kanit_gercektir(self):
        for i in self.global_items:
            self.assertGreaterEqual(len(i["gold_kaynak_spanlar"]), 3, i["id"])
            self.assertTrue(i["gold_sayfalar"], i["id"])
            self.assertTrue(i["gold_cevap"].strip(), i["id"])

    def test_kitabin_tamamina_yayilir(self):
        """Adayları baştan kesmek 22 item'ın hepsini ilk temadan alıyordu;
        `global` ölçümü kitabın yalnız üçte birini görüyordu."""
        sayfalar = [i["gold_sayfalar"][0] for i in self.global_items]
        self.assertGreater(max(sayfalar) - min(sayfalar), 80,
                           "global item'lar kitabin tek bolgesinde toplanmis")


class MultiTurnAlanTests(unittest.TestCase):
    """Alan adı uyuşmazlığı ölçümü sıfırlamıştı."""

    @classmethod
    def setUpClass(cls):
        import json
        import os
        yol = os.path.join("tests", "golden", "golden_10biy_v2.json")
        if not os.path.isfile(yol):
            raise unittest.SkipTest("golden set uretilmemis")
        veri = json.load(open(yol, encoding="utf-8"))
        cls.items = [i for i in veri["items"] if i["senaryo"] == "multi_turn"]

    def test_gecmis_alani_runner_ile_ayni_adi_tasir(self):
        # Üretici `gecmis`, runner `konusma_gecmisi` okuyordu: geçmiş hiç
        # ulaşmıyordu ve multi_turn recall@5 = 0,000 çıkıyordu.
        for i in self.items:
            self.assertTrue(i.get("konusma_gecmisi"), i["id"])


if __name__ == "__main__":
    unittest.main()
