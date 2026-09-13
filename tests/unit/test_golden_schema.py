"""#64 (EXP-010/EVAL-01+04+10+11) — golden set şema v2 doğrulayıcısı.

ÖLÇÜLEN DURUM (v1): 27 item `senaryo=null`; kimya/fizik setlerinde `senaryo`
ve dolu `unite` **hiç yok** → o setlerde **judge n=0** (ölçüm hiç yapılmıyordu);
`hop_sayisi`/`grup_id`/`risk`/... alanları yok; 22/22 `variant` gruplanmamış →
aynı soru birden çok kez sayılıp metriği şişiriyordu.

BU TESTİN AMACI: bu hataların **otomatik yakalanması**. Denetim raporunun
kendi ifadesiyle: *"Bu test bugün yazılsa EVAL-01 ve EVAL-10 otomatik
yakalanırdı."* Aşağıdaki `RealGoldenFilesTests` bunu kanıtlıyor.
"""
import json
import os
import unittest

from src.eval.golden_schema import (HEDEF_DAGILIM, SENARYOLAR, upgrade_item,
                                    validate, validate_item,
                                    ValidationReport)

_GOLDEN = os.path.join("tests", "golden")


def _item(**kw):
    """v2 şemasına uyan geçerli bir temel item."""
    d = {
        "id": "t-001", "kazanim_kod": "10.1.1.1", "unite": "Ekoloji",
        "soru": "Ekosistem nedir?", "gold_kaynak_spanlar": ["d#10.0"],
        "gold_sayfalar": [10], "gold_cevap": "Ekosistem ...",
        "kategori": "kolay", "beklenen_davranis": "cevapla",
        "senaryo": "direct", "hop_sayisi": 1, "grup_id": None,
        "kabul_edilebilir_sayfalar": [], "yasakli_kaynaklar": [],
        "beklenen_reason_prefix": None, "gorsel_bagimliligi": False,
        "hard_negative_turu": None, "risk": "dusuk", "uzman_uyusmasi": 1.0,
    }
    d.update(kw)
    return d


class ValidItemTests(unittest.TestCase):
    def test_baseline_item_is_valid(self):
        r = validate([_item()], check_distribution=False)
        self.assertTrue(r.valid, [str(e) for e in r.errors])


class RequiredFieldTests(unittest.TestCase):
    def _hatalar(self, **kw):
        r = ValidationReport()
        validate_item(_item(**kw), r)
        return {e.field for e in r.errors}

    def test_missing_senaryo_is_an_error(self):
        """v1'in ASIL hatası: 27 item etiketsizdi ve judge örneklemesi onları
        hiç görmüyordu."""
        self.assertIn("senaryo", self._hatalar(senaryo=None))

    def test_unknown_senaryo_is_rejected(self):
        self.assertIn("senaryo", self._hatalar(senaryo="uydurma"))

    def test_empty_unite_is_an_error(self):
        """Kimya/fizik setlerinde boştu → o setlerde judge n=0."""
        self.assertIn("unite", self._hatalar(unite=""))

    def test_answer_item_needs_gold_evidence(self):
        for alan in ("gold_kaynak_spanlar", "gold_sayfalar", "gold_cevap"):
            with self.subTest(alan):
                bos = [] if "cevap" not in alan else ""
                self.assertIn(alan, self._hatalar(**{alan: bos}))

    def test_non_answer_item_needs_expected_reason(self):
        h = self._hatalar(beklenen_davranis="cekimser", senaryo="out_of_scope",
                          beklenen_reason_prefix=None)
        self.assertIn("beklenen_reason_prefix", h)

    def test_unknown_reason_prefix_is_rejected(self):
        h = self._hatalar(beklenen_davranis="reddet", senaryo="harmful",
                          beklenen_reason_prefix="uydurma_sebep")
        self.assertIn("beklenen_reason_prefix", h)

    def test_new_v2_fields_are_required(self):
        for alan, deger in (("hop_sayisi", None), ("risk", None),
                            ("gorsel_bagimliligi", None),
                            ("kabul_edilebilir_sayfalar", None),
                            ("yasakli_kaynaklar", None)):
            with self.subTest(alan):
                self.assertIn(alan, self._hatalar(**{alan: deger}))

    def test_invalid_behaviour_is_rejected(self):
        self.assertIn("beklenen_davranis", self._hatalar(beklenen_davranis="belki"))

    def test_expert_agreement_must_be_a_ratio(self):
        self.assertIn("uzman_uyusmasi", self._hatalar(uzman_uyusmasi=1.7))
        r = ValidationReport()
        validate_item(_item(uzman_uyusmasi=None), r)
        self.assertNotIn("uzman_uyusmasi", {e.field for e in r.errors})


class ScenarioConsistencyTests(unittest.TestCase):
    def test_multi_hop_needs_two_pages(self):
        r = validate([_item(senaryo="multi_hop", hop_sayisi=2,
                            gold_sayfalar=[10], gold_kaynak_spanlar=["d#10.0"])],
                     check_distribution=False)
        self.assertIn("gold_sayfalar", {e.field for e in r.errors})

    def test_multi_hop_needs_hop_count_at_least_two(self):
        r = validate([_item(senaryo="multi_hop", hop_sayisi=1,
                            gold_sayfalar=[10, 12],
                            gold_kaynak_spanlar=["d#10.0", "d#12.0"])],
                     check_distribution=False)
        self.assertIn("hop_sayisi", {e.field for e in r.errors})

    def test_valid_multi_hop_passes(self):
        r = validate([_item(senaryo="multi_hop", hop_sayisi=2,
                            gold_sayfalar=[10, 12],
                            gold_kaynak_spanlar=["d#10.0", "d#12.0"])],
                     check_distribution=False)
        self.assertTrue(r.valid, [str(e) for e in r.errors])

    def test_hard_negative_needs_a_type(self):
        r = validate([_item(senaryo="hard_negative", hard_negative_turu=None)],
                     check_distribution=False)
        self.assertIn("hard_negative_turu", {e.field for e in r.errors})

    def test_visual_item_without_figure_scenario_warns(self):
        r = validate([_item(gorsel_bagimliligi=True, senaryo="direct")],
                     check_distribution=False)
        self.assertTrue(any(w.field == "gorsel_bagimliligi" for w in r.warnings))


class GroupingTests(unittest.TestCase):
    """v1'de 22/22 varyant gruplanmamıştı → aynı soru birden çok kez sayılıp
    metriği şişiriyordu."""

    def test_variant_without_group_is_an_error(self):
        r = validate([_item(senaryo="variant", grup_id=None)],
                     check_distribution=False)
        self.assertIn("grup_id", {e.field for e in r.errors})

    def test_variant_with_group_passes(self):
        r = validate([_item(id="a", senaryo="direct", grup_id="g1"),
                      _item(id="b", senaryo="variant", grup_id="g1")],
                     check_distribution=False)
        self.assertTrue(r.valid, [str(e) for e in r.errors])

    def test_group_spanning_two_objectives_warns(self):
        r = validate([_item(id="a", grup_id="g1", kazanim_kod="10.1.1.1"),
                      _item(id="b", grup_id="g1", kazanim_kod="10.2.2.2")],
                     check_distribution=False)
        self.assertTrue(any(w.field == "grup_id" for w in r.warnings))

    def test_duplicate_ids_are_rejected(self):
        r = validate([_item(id="ayni"), _item(id="ayni")],
                     check_distribution=False)
        self.assertIn("id", {e.field for e in r.errors})


class DistributionTests(unittest.TestCase):
    def test_missing_categories_are_warned(self):
        r = validate([_item(id=f"t{i}") for i in range(20)])
        alanlar = {w.field for w in r.warnings}
        self.assertIn("dagilim", alanlar)

    def test_distribution_is_reported(self):
        r = validate([_item(id="a"), _item(id="b", senaryo="harmful",
                                           beklenen_davranis="reddet",
                                           beklenen_reason_prefix="guard_",
                                           gold_kaynak_spanlar=[],
                                           gold_sayfalar=[], gold_cevap="")],
                     check_distribution=False)
        self.assertAlmostEqual(r.distribution["direct"], 0.5)

    def test_targets_sum_to_a_sane_share(self):
        """Hedef dağılım toplamı 1'i aşmamalı — aşarsa set kurulamaz."""
        self.assertLess(sum(HEDEF_DAGILIM.values()), 1.0)

    def test_every_target_category_is_in_the_taxonomy(self):
        for k in HEDEF_DAGILIM:
            self.assertIn(k, SENARYOLAR)


class UpgradeTests(unittest.TestCase):
    """v1 → v2 taşıma UYDURMAZ: çıkarılamayan alan None kalır ve hata verir."""

    def test_scenario_is_derived_from_category_when_possible(self):
        y = upgrade_item({"id": "x", "kategori": "edge_zararli",
                          "beklenen_davranis": "reddet"})
        self.assertEqual(y["senaryo"], "harmful")

    def test_unknown_category_leaves_scenario_none(self):
        """Sessizce 'direct' atamak, etiketsiz item'ı geçerli göstermek olurdu."""
        y = upgrade_item({"id": "x", "kategori": "bilinmeyen"})
        self.assertIsNone(y["senaryo"])
        r = ValidationReport()
        validate_item(y, r)
        self.assertIn("senaryo", {e.field for e in r.errors})

    def test_hop_count_is_derived_from_distinct_pages(self):
        y = upgrade_item({"id": "x", "gold_sayfalar": [3, 3, 7]})
        self.assertEqual(y["hop_sayisi"], 2)

    def test_defaults_do_not_invent_evidence(self):
        y = upgrade_item({"id": "x"})
        self.assertEqual(y["kabul_edilebilir_sayfalar"], [])
        self.assertEqual(y["yasakli_kaynaklar"], [])
        self.assertIsNone(y["uzman_uyusmasi"])


class RealGoldenFilesTests(unittest.TestCase):
    """Denetimin iddiasını KANITLAR: bu test v1'de yazılsaydı EVAL-01 ve
    EVAL-10 otomatik yakalanırdı."""

    def _yukle(self, ad):
        yol = os.path.join(_GOLDEN, ad)
        if not os.path.isfile(yol):
            self.skipTest(f"{ad} yok")
        with open(yol, encoding="utf-8") as fh:
            d = json.load(fh)
        return d["items"] if isinstance(d, dict) and "items" in d else d

    def test_v1_bio_fails_v2_schema(self):
        r = validate(self._yukle("golden_12bio_v1.json"))
        self.assertFalse(r.valid)
        self.assertIn("senaryo", {e.field for e in r.errors},
                      "27 etiketsiz item yakalanmadı")

    def test_v1_physics_has_no_scenario_labels_at_all(self):
        """Bu setlerde judge n=0 idi — yani ölçüm hiç yapılmıyordu."""
        items = self._yukle("golden_12fizik_v1.json")
        r = validate(items)
        senaryosuz = sum(1 for e in r.errors if e.field == "senaryo")
        self.assertEqual(senaryosuz, len(items))

    def test_v1_chemistry_has_no_unit_labels(self):
        items = self._yukle("golden_12kimya_v1.json")
        r = validate(items)
        unitesiz = sum(1 for e in r.errors if e.field == "unite")
        self.assertEqual(unitesiz, len(items))

    def test_v2_files_if_present_must_pass(self):
        """v2 üretildikçe bu test onları koruyacak."""
        for ad in sorted(os.listdir(_GOLDEN)) if os.path.isdir(_GOLDEN) else []:
            if not ad.endswith(".json") or "_v2" not in ad:
                continue
            with self.subTest(ad):
                r = validate(self._yukle(ad))
                self.assertTrue(r.valid, [str(e) for e in r.errors[:5]])


class DevFrozenSplitTests(unittest.TestCase):
    """#71 — test kirlenmesi: eşik ayarlamak golden set üzerinde yapılıyorsa,
    o set artık bağımsız bir ölçüm değildir; **ayarladığın şeyle ölçüyorsun**
    ve kapı değerleri sistematik olarak iyimser çıkar."""

    def _set(self, n_per=6):
        from src.eval.golden_schema import SENARYOLAR
        items = []
        for s in sorted(SENARYOLAR):
            for i in range(n_per):
                items.append(_item(id=f"{s}-{i}", senaryo=s,
                                   grup_id="g" if s == "variant" else None,
                                   hard_negative_turu=("yakin_konu"
                                                       if s == "hard_negative"
                                                       else None),
                                   hop_sayisi=2 if s == "multi_hop" else 1,
                                   gold_sayfalar=[10, 12] if s == "multi_hop" else [10],
                                   gold_kaynak_spanlar=["d#10.0", "d#12.0"]
                                   if s == "multi_hop" else ["d#10.0"]))
        return items

    def test_split_is_deterministic(self):
        """Yeniden bölerek 'daha iyi' bir ayrım aramak da bir kirlenmedir."""
        from src.eval.golden_schema import split_dev_frozen
        a1, b1 = split_dev_frozen(self._set())
        a2, b2 = split_dev_frozen(self._set())
        self.assertEqual([i["id"] for i in a1], [i["id"] for i in a2])
        self.assertEqual([i["id"] for i in b1], [i["id"] for i in b2])

    def test_sides_do_not_overlap(self):
        from src.eval.golden_schema import split_dev_frozen
        dev, frozen = split_dev_frozen(self._set())
        self.assertFalse({i["id"] for i in dev} & {i["id"] for i in frozen})

    def test_nothing_is_lost(self):
        from src.eval.golden_schema import split_dev_frozen
        items = self._set()
        dev, frozen = split_dev_frozen(items)
        self.assertEqual(len(dev) + len(frozen), len(items))

    def test_split_is_stratified(self):
        """Tabakalı olmazsa nadir kategoriler (adversarial n=5) tek tarafa
        düşer ve diğer tarafta HİÇ ölçülemez."""
        from src.eval.golden_schema import split_report
        r = split_report(self._set(n_per=4))
        self.assertEqual(r["empty_side"], [],
                         f"tek tarafa düşen kategori: {r['empty_side']}")

    def test_changing_the_salt_changes_the_split(self):
        """Salt değiştirmek BİLİNÇLİ bir karardır ve yeni golden sürümü
        gerektirir — eski ölçümler karşılaştırılamaz hâle gelir."""
        from src.eval.golden_schema import split_dev_frozen
        a, _ = split_dev_frozen(self._set(), salt="x")
        b, _ = split_dev_frozen(self._set(), salt="y")
        self.assertNotEqual([i["id"] for i in a], [i["id"] for i in b])

    def test_real_v2_set_splits_cleanly(self):
        import json
        yol = os.path.join(_GOLDEN, "golden_10biy_v2.json")
        if not os.path.isfile(yol):
            self.skipTest("golden v2 yok")
        from src.eval.golden_schema import split_report
        with open(yol, encoding="utf-8") as fh:
            items = json.load(fh)["items"]
        r = split_report(items)
        self.assertEqual(r["empty_side"], [])
        self.assertGreater(r["n_dev"], 50)
        self.assertGreater(r["n_frozen"], 50)


if __name__ == "__main__":
    unittest.main()
