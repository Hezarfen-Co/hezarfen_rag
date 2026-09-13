"""#60 — çekimserlik eşiği kalibrasyon ARACININ testleri (EXP-017).

Araç eşik SEÇMEZ, ödünleşimi ölçer. Bu dosya ölçümün doğru yapıldığını
sınar; eşiğin kendisi bir ürün kararıdır.

En kritik iki test:
  - Guard'ın reddettiği item'lar hesaba KATILMAMALI. Onlar eşikten bağımsız
    reddedilir; saymak eşiği olduğundan iyi gösterirdi.
  - Bağlam hiç gelmediğinde (top_score None) item eşikten BAĞIMSIZ çekimser
    sayılmalı. `None < esik` karşılaştırması Python'da TypeError atardı;
    sessizce "geçti" saymak ise yanlış çekimserliği gizlerdi.
"""
import unittest

from src.eval.abstain_calibration import (ANSWERABLE, GUARD_OWNED, UNANSWERABLE,
                                          ItemScore, candidates,
                                          n_needed_to_separate, report, sweep)


def _s(sid, senaryo, expected, score, guard=False):
    return ItemScore(sid, senaryo, expected, score, guard)


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.scores = [
            _s("a", "direct", "cevapla", 0.90),
            _s("b", "direct", "cevapla", 0.40),
            _s("c", "synthesis", "cevapla", 0.70),
            _s("d", "unanswerable", "cekimser", 0.10),
            _s("e", "hard_negative", "cekimser", 0.80),
            _s("f", "out_of_scope", "cekimser", 0.20),
        ]

    def _at(self, esik):
        for p in sweep(self.scores, step=0.1):
            if abs(p.threshold - esik) < 1e-6:
                return p
        raise AssertionError(f"{esik} noktasi yok")

    def test_zero_threshold_answers_everything(self):
        p = self._at(0.0)
        self.assertEqual(p.false_abstentions, 0)
        self.assertEqual(p.false_answers, 3)

    def test_high_threshold_abstains_from_everything(self):
        p = self._at(1.0)
        self.assertEqual(p.false_abstentions, 3)
        self.assertEqual(p.false_answers, 0)

    def test_rates_use_the_right_denominators(self):
        p = self._at(0.5)
        self.assertEqual(p.n_answerable, 3)
        self.assertEqual(p.n_unanswerable, 3)
        self.assertAlmostEqual(p.false_abstention_rate, 1 / 3)
        self.assertAlmostEqual(p.false_answer_rate, 1 / 3)

    def test_the_curve_is_monotone(self):
        """Eşik yükseldikçe yanlış çekimserlik ARTAR, yanlış cevap AZALIR.
        Aksi bir eğri hesapta hata demektir."""
        ps = sweep(self.scores, step=0.05)
        for a, b in zip(ps, ps[1:]):
            self.assertLessEqual(a.false_abstentions, b.false_abstentions)
            self.assertGreaterEqual(a.false_answers, b.false_answers)

    def test_guard_blocked_items_are_excluded(self):
        """Guard'ın yakaladıkları retrieval'a hiç ulaşmaz."""
        kirli = self.scores + [_s("g", "harmful", "cekimser", 0.99, guard=True),
                               _s("h", "injection", "cekimser", 0.99, guard=True)]
        self.assertEqual(self._at(0.5).n_unanswerable,
                         sweep(kirli, step=0.1)[5].n_unanswerable)

    def test_missing_context_counts_as_abstention_at_every_threshold(self):
        s = [_s("x", "direct", "cevapla", None)]
        for p in sweep(s, step=0.25):
            with self.subTest(p.threshold):
                self.assertEqual(p.false_abstentions, 1)

    def test_missing_context_is_never_a_false_answer(self):
        s = [_s("x", "unanswerable", "cekimser", None)]
        for p in sweep(s, step=0.25):
            with self.subTest(p.threshold):
                self.assertEqual(p.false_answers, 0)

    def test_scenario_sets_do_not_overlap(self):
        self.assertFalse(ANSWERABLE & UNANSWERABLE)
        self.assertFalse(ANSWERABLE & GUARD_OWNED)
        self.assertFalse(UNANSWERABLE & GUARD_OWNED)

    def test_unlabelled_scenarios_are_not_silently_counted(self):
        """Yeni bir senaryo türü eklenirse sessizce bir kovaya düşmemeli."""
        s = self.scores + [_s("z", "yeni_senaryo", "cevapla", 0.05)]
        self.assertEqual(sweep(s, step=0.1)[5].n_answerable,
                         self._at(0.5).n_answerable)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.points = sweep([
            _s("a", "direct", "cevapla", 0.90),
            _s("b", "direct", "cevapla", 0.60),
            _s("c", "unanswerable", "cekimser", 0.10),
            _s("d", "hard_negative", "cekimser", 0.50),
        ], step=0.05)

    def test_three_priorities_are_offered_not_one_answer(self):
        """Hangi önceliğin doğru olduğu bir ÜRÜN kararıdır, hesap değil."""
        c = candidates(self.points)
        self.assertEqual(set(c), {"min_false_answer_under_cap",
                                  "min_total_error", "zero_false_abstention"})

    def test_zero_false_abstention_really_has_none(self):
        c = candidates(self.points)["zero_false_abstention"]
        self.assertEqual(c["false_abstentions"], 0)

    def test_cap_is_respected(self):
        c = candidates(self.points, max_false_abstention=0.0)
        self.assertEqual(c["min_false_answer_under_cap"]["false_abstentions"], 0)

    def test_impossible_constraint_returns_none_not_a_wrong_answer(self):
        """Kısıtı sağlayan eşik yoksa araç bir şey UYDURMAMALI."""
        ps = sweep([_s("a", "direct", "cevapla", None),
                    _s("c", "unanswerable", "cekimser", 0.9)], step=0.1)
        self.assertIsNone(candidates(ps, max_false_abstention=0.0)
                          ["min_false_answer_under_cap"])

    def test_no_verdict_is_emitted(self):
        for d in candidates(self.points).values():
            if d:
                for yasak in ("passed", "chosen", "recommended", "best"):
                    self.assertNotIn(yasak, d)


class SampleSizeTests(unittest.TestCase):
    """Kalibrasyonun ASIL çıktısı bir eşik değil, bu sayı oldu."""

    def test_smaller_difference_needs_more_items(self):
        self.assertGreater(n_needed_to_separate(0.115, 0.077),
                           n_needed_to_separate(0.115, 0.038))

    def test_identical_rates_cannot_be_separated(self):
        self.assertEqual(n_needed_to_separate(0.1, 0.1), -1)

    def test_measured_case_is_far_beyond_the_current_set(self):
        """ÖLÇÜLDÜ: 0,30 -> 0,49 farkini ayirt etmek 1844 cevapsiz item
        gerektiriyor; elimizde 26 var."""
        self.assertGreater(n_needed_to_separate(0.115, 0.077), 1000)


class ReportTests(unittest.TestCase):
    def test_scenario_distribution_is_reported(self):
        r = report([_s("a", "direct", "cevapla", 0.9),
                    _s("b", "direct", "cevapla", 0.5),
                    _s("c", "unanswerable", "cekimser", 0.1)], step=0.25)
        self.assertEqual(r.by_scenario["direct"]["n"], 2)
        self.assertEqual(r.by_scenario["direct"]["min"], 0.5)
        self.assertEqual(r.by_scenario["direct"]["max"], 0.9)

    def test_counts_are_surfaced_not_hidden(self):
        r = report([_s("a", "harmful", "cekimser", None, guard=True),
                    _s("b", "direct", "cevapla", None)], step=0.5)
        self.assertEqual(r.guard_blocked, 1)
        self.assertEqual(r.no_context, 1)

    def test_report_is_json_serialisable(self):
        import json
        json.dumps(report([_s("a", "direct", "cevapla", 0.9)], step=0.5).to_dict())


class ProductionDefaultTests(unittest.TestCase):
    """Eval ile üretim AYNI eşiği okumalı (ACC-10'un tekrarı olmasın).

    ACC-10'da ölçülmüştü: `runner` parent genişletmeyi AÇIK, `http_app` KAPALI
    kullanıyordu — yayınlanan skorlar üretimi temsil etmiyordu. Eşik de kodun
    iki yerinde ayrı ayrı `0.30` yazılıydı; biri değişse fark edilmezdi.
    """

    def _generator(self, **kw):
        from src.generate import Generator
        from tests.unit.test_cache_invalidation import _LLM, _Reranker, _Retriever
        return Generator(_Retriever([]), _Reranker({}), {}, {}, _LLM(),
                         ders="biyoloji", cost_recorder=lambda **k: None, **kw)

    def test_default_comes_from_the_shared_constant(self):
        from src.generate.generator import ABSTAIN_SCORE_DEFAULT
        self.assertIsInstance(ABSTAIN_SCORE_DEFAULT, float)
        self.assertTrue(0.0 <= ABSTAIN_SCORE_DEFAULT <= 1.0)
        self.assertAlmostEqual(self._generator().abstain_score,
                               ABSTAIN_SCORE_DEFAULT)

    def test_eval_and_production_read_the_same_default(self):
        """`runner.build_pipeline` eskiden kendi `0.30`'unu yazıyordu."""
        import inspect

        from src.eval import runner
        kaynak = inspect.getsource(runner.build_pipeline)
        self.assertNotIn("abstain_score=0.30", kaynak,
                         "eval kendi esigini yaziyor -- uretimden ayrisabilir")

    def test_explicit_argument_wins_over_the_default(self):
        self.assertAlmostEqual(self._generator(abstain_score=0.77).abstain_score,
                               0.77)

    def test_zero_is_honoured_not_treated_as_missing(self):
        """`abstain_score=0` "eşik yok" demektir ve geçerli bir ayardır;
        `or` ile yazılsaydı sessizce varsayılana düşerdi."""
        self.assertAlmostEqual(self._generator(abstain_score=0.0).abstain_score,
                               0.0)

    def test_env_overrides_the_default(self):
        """Env okuması AYRI bir fonksiyondadır; modülü `importlib.reload` ile
        sınamak bu modülde ALAKASIZ testleri kırar (reload `_USE_INIT_ROLE`
        sentinel'inin yeni bir örneğini yaratır, kimlik kontrolleri bozulur)."""
        import os
        from unittest import mock

        from src.generate.generator import _env_abstain_score
        with mock.patch.dict(os.environ, {"RAG_ABSTAIN_SCORE": "0.55"}):
            self.assertAlmostEqual(_env_abstain_score(), 0.55)

    def test_missing_env_uses_the_default(self):
        import os
        from unittest import mock

        from src.generate.generator import _env_abstain_score
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertAlmostEqual(_env_abstain_score(), 0.30)

    def test_broken_env_falls_back_instead_of_crashing(self):
        """Yanlış yazılmış bir ortam değişkeni servisi açılışta çökertmemeli."""
        import os
        from unittest import mock

        from src.generate.generator import _env_abstain_score
        for bozuk in ("", "yuksek", "0,45", "None"):
            with self.subTest(bozuk=bozuk):
                with mock.patch.dict(os.environ, {"RAG_ABSTAIN_SCORE": bozuk}):
                    self.assertAlmostEqual(_env_abstain_score(), 0.30)

    def test_out_of_range_env_is_refused(self):
        """1,5 sessizce kabul edilse ürün HER soruya çekimser kalırdı;
        -1 ise eşiği tamamen kapatırdı."""
        import os
        from unittest import mock

        from src.generate.generator import _env_abstain_score
        for disarida in ("1.5", "-0.2", "42"):
            with self.subTest(deger=disarida):
                with mock.patch.dict(os.environ, {"RAG_ABSTAIN_SCORE": disarida}):
                    self.assertAlmostEqual(_env_abstain_score(), 0.30)

    def test_current_default_is_still_the_measured_one(self):
        """EXP-017 esigi DEGISTIRMEDI: 0,30 ile 0,49 farkini ayirt etmek 1844
        cevapsiz item gerektiriyor, elimizde 26 var."""
        from src.generate.generator import ABSTAIN_SCORE_DEFAULT
        self.assertAlmostEqual(ABSTAIN_SCORE_DEFAULT, 0.30)


if __name__ == "__main__":
    unittest.main()
