"""M0-2 (#34) — survivorship bias testleri.

NEDEN bu dosya var (EXP-010/EVAL-05): `_eval_item` çekimser kalan bir `cevapla`
item'ına `judge={"skipped": True}` yazıyor, `_aggregate` de onu hakem
ortalamasının PAYDASINDAN düşürüyordu. Oysa "cevap üretemedi" en ciddi kalite
hatasıdır — 0 puan alması gerekir, metrikten silinmesi değil.

Gerçek örnek: v1.1 koşumunda `bio12-v1-mt008` aynı anda (a) yanlış-abstain
listesinde, (b) faithfulness ortalamasından silinmiş durumdaydı. Doğru sayılsa
faithfulness 0.988 -> 0.942 olurdu (CI-alt ~0.86).

Ters teşvik: abstain oranı arttıkça `faithfulness_answered` YÜKSELİR. Bu yüzden
artık iki sayı birlikte raporlanır ve `answerable_coverage` bağlamı verir.
"""
import unittest

from src.eval.runner import _aggregate


def _item(item_id, *, beklenen="cevapla", abstained=False, judge=None, error=None):
    """_aggregate'in beklediği en küçük item şekli."""
    return {
        "id": item_id,
        "kategori": "orta",
        "beklenen_davranis": beklenen,
        "retrieval": {},
        "citation": {},
        "guardrail": {"passed": None, "fail_closed": None,
                      "abstained": abstained, "reason": ""},
        "generation": {},
        "judge": judge,
        "error": error,
    }


def _scored(faith, rel=1.0, corr=1.0):
    return {"faithfulness": faith, "answer_relevancy": rel, "answer_correctness": corr}


_SKIPPED = {"skipped": True, "reason": "cevap abstain oldu"}


class SurvivorshipTests(unittest.TestCase):
    def test_skipped_item_no_longer_vanishes(self):
        """Çekimser item penalized ortalamasına 0.0 olarak GİRER."""
        subset = [_item("a", judge=_scored(1.0)),
                  _item("b", judge=_scored(1.0)),
                  _item("c", abstained=True, judge=_SKIPPED)]
        j = _aggregate(subset)["judge"]
        self.assertEqual(j["n_judged"], 2)
        self.assertEqual(j["n_judge_skipped_abstained"], 1)
        self.assertEqual(j["n_judge_selected"], 3)
        self.assertAlmostEqual(j["faithfulness_answered"], 1.0)
        self.assertAlmostEqual(j["faithfulness_penalized"], 2 / 3)   # (1+1+0)/3

    def test_reproduces_the_real_regression_number(self):
        """EVAL-05'in sayısı: n=21'de ort 0.988, bir 0.0 eklenince 0.942."""
        # 21 item, ortalaması 0.988 olacak şekilde
        vals = [0.988] * 21
        subset = [_item(f"i{k}", judge=_scored(v)) for k, v in enumerate(vals)]
        subset.append(_item("mt008", abstained=True, judge=_SKIPPED))
        j = _aggregate(subset)["judge"]
        self.assertAlmostEqual(j["faithfulness_answered"], 0.988, places=6)
        self.assertAlmostEqual(j["faithfulness_penalized"], 0.988 * 21 / 22, places=3)
        self.assertAlmostEqual(j["faithfulness_penalized"], 0.943, places=3)
        # answered ile penalized arasındaki fark GÖRÜNÜR olmalı
        self.assertGreater(j["faithfulness_answered"] - j["faithfulness_penalized"], 0.04)

    def test_perverse_incentive_is_now_visible(self):
        """Daha çok abstain -> answered YÜKSELİR ama penalized DÜŞER.
        Metriğin ters teşvik ürettiği tam olarak bu; artık iki sayı ayrışıyor."""
        az_abstain = [_item("a", judge=_scored(0.9)), _item("b", judge=_scored(0.5)),
                      _item("c", judge=_scored(0.9))]
        cok_abstain = [_item("a", judge=_scored(0.9)),
                       _item("b", abstained=True, judge=_SKIPPED),   # zayıf olan kaçtı
                       _item("c", judge=_scored(0.9))]
        j1 = _aggregate(az_abstain)["judge"]
        j2 = _aggregate(cok_abstain)["judge"]
        self.assertGreater(j2["faithfulness_answered"], j1["faithfulness_answered"])
        self.assertLess(j2["faithfulness_penalized"], j1["faithfulness_penalized"])

    def test_answerable_coverage(self):
        subset = [_item("a"), _item("b"), _item("c", abstained=True),
                  _item("e1", beklenen="cekimser", abstained=True)]
        j = _aggregate(subset)["judge"]
        # `cevapla` item 3 tane, 2'si cevaplandı -> 2/3
        self.assertEqual(j["n_answerable"], 3)
        self.assertAlmostEqual(j["answerable_coverage"], 2 / 3)

    def test_coverage_ignores_non_answerable_items(self):
        """Kapsam-dışı/zararlı item'ların çekimserliği coverage'ı DÜŞÜRMEZ."""
        subset = [_item("a"), _item("r1", beklenen="red", abstained=True),
                  _item("e1", beklenen="cekimser", abstained=True)]
        j = _aggregate(subset)["judge"]
        self.assertEqual(j["n_answerable"], 1)
        self.assertAlmostEqual(j["answerable_coverage"], 1.0)

    def test_no_answerable_items_gives_none(self):
        subset = [_item("r1", beklenen="red", abstained=True)]
        j = _aggregate(subset)["judge"]
        self.assertIsNone(j["answerable_coverage"])
        self.assertEqual(j["n_answerable"], 0)

    def test_all_skipped(self):
        subset = [_item("a", abstained=True, judge=_SKIPPED),
                  _item("b", abstained=True, judge=_SKIPPED)]
        j = _aggregate(subset)["judge"]
        self.assertIsNone(j["faithfulness_answered"])      # hiç ölçüm yok
        self.assertAlmostEqual(j["faithfulness_penalized"], 0.0)  # ama hepsi başarısız
        self.assertAlmostEqual(j["answerable_coverage"], 0.0)

    def test_no_judge_at_all(self):
        subset = [_item("a"), _item("b")]
        j = _aggregate(subset)["judge"]
        self.assertEqual(j["n_judged"], 0)
        self.assertEqual(j["n_judge_skipped_abstained"], 0)
        self.assertIsNone(j["faithfulness_penalized"])

    def test_judge_error_none_score_not_counted_as_zero(self):
        """Hakem HATASI (skor None) ile çekimserlik KARIŞTIRILMAZ:
        hata ölçüm eksikliğidir, 0.0 değil (#29 davranışı korunur)."""
        subset = [_item("a", judge=_scored(1.0)),
                  _item("b", judge={"faithfulness": None, "answer_relevancy": None,
                                    "answer_correctness": None, "errors": ["timeout"]})]
        j = _aggregate(subset)["judge"]
        self.assertEqual(j["n_judged"], 2)
        self.assertEqual(j["faithfulness_n"], 1)           # katkı veren 1 item
        self.assertEqual(j["n_errors"], 1)
        self.assertAlmostEqual(j["faithfulness_answered"], 1.0)
        self.assertAlmostEqual(j["faithfulness_penalized"], 1.0)  # 0.0 EKLENMEDİ

    def test_backward_compatible_keys_kept(self):
        """Eski anahtarlar korunur (mevcut raporlarla kıyaslanabilirlik)."""
        subset = [_item("a", judge=_scored(0.8))]
        j = _aggregate(subset)["judge"]
        for k in ("faithfulness", "answer_relevancy", "answer_correctness",
                  "n_judged", "n_errors", "faithfulness_n"):
            self.assertIn(k, j)
        self.assertAlmostEqual(j["faithfulness"], 0.8)


if __name__ == "__main__":
    unittest.main()
