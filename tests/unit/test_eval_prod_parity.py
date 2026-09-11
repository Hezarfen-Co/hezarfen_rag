"""M0-7 (#39) — eval ↔ üretim pipeline eşitliği testleri.

NEDEN (EXP-010/ACC-10): `service/http_app.build_service` `chunks_by_id`'ye
**yalnız child** chunk koyuyordu; `rerank_select`'teki
`ch.parent_id in chunks_by_id` kontrolü bu yüzden daima False oluyor ve
**parent genişletme üretimde sessizce KAPALI** kalıyordu. `eval/runner.build_pipeline`
ise child+parent koyuyordu → **AÇIK**.

Sonuç: yayınlanmış `citation precision 0.645` / `recall 0.883` sayıları üretimde
koşan boru hattını **temsil etmiyordu** — ve bu ayrışma hiçbir yerde kayıtlı değildi.

Bu testler ayrışmanın bir daha sessizce oluşamayacağını sabitler.
"""
import os
import unittest
from unittest import mock


class SharedFlagTests(unittest.TestCase):
    def test_single_source_of_truth_exists(self):
        from src.service.http_app import INCLUDE_PARENTS_DEFAULT
        self.assertIsInstance(INCLUDE_PARENTS_DEFAULT, bool)

    def test_runner_reads_the_same_flag(self):
        """Asıl iddia: eval kendi başına karar VERMEZ, aynı anahtarı okur."""
        import inspect
        from src.eval import runner as R
        src = inspect.getsource(R.build_pipeline)
        self.assertIn("INCLUDE_PARENTS_DEFAULT", src)
        # eski kosulsuz hal geri gelmesin
        self.assertNotIn('chunks_by_id = {c.chunk_id: c for c in chunks}', src)

    def test_default_matches_production_behaviour(self):
        """Varsayılan, üretimin BUGÜNKÜ davranışı (parent KAPALI) olmalı —
        davranışı ölçmeden değiştirmek kabul paketini ihlal eder."""
        from src.service.http_app import INCLUDE_PARENTS_DEFAULT
        self.assertFalse(INCLUDE_PARENTS_DEFAULT)

    def test_env_can_reproduce_historical_runs(self):
        """Geçmiş ölçümler parent AÇIK ile alınmıştı; yeniden üretilebilmeli."""
        import importlib
        from src.service import http_app
        try:
            with mock.patch.dict(os.environ, {"RAG_INCLUDE_PARENTS": "1"}):
                importlib.reload(http_app)
                self.assertTrue(http_app.INCLUDE_PARENTS_DEFAULT)
        finally:
            importlib.reload(http_app)
        self.assertFalse(http_app.INCLUDE_PARENTS_DEFAULT)

    def test_falsey_values_are_off(self):
        import importlib
        from src.service import http_app
        try:
            for val in ("0", "", "false", "False"):
                with mock.patch.dict(os.environ, {"RAG_INCLUDE_PARENTS": val}):
                    importlib.reload(http_app)
                    self.assertFalse(http_app.INCLUDE_PARENTS_DEFAULT, f"val={val!r}")
        finally:
            importlib.reload(http_app)


class BuildServiceSignatureTests(unittest.TestCase):
    def test_include_parents_is_an_explicit_parameter(self):
        """Bayrak çağrı yerinde de açıkça verilebilmeli (A/B için)."""
        import inspect
        from src.service.http_app import build_service
        sig = inspect.signature(build_service)
        self.assertIn("include_parents", sig.parameters)
        self.assertIsNone(sig.parameters["include_parents"].default)


class RerankSelectContractTests(unittest.TestCase):
    """Ayrışmanın MEKANİZMASINI sabitler: parent genişletme yalnız parent
    chunk `chunks_by_id`'de varsa devreye giriyor."""

    def _fixture(self, include_parents: bool):
        from dataclasses import dataclass, field
        from src.rerank.pipeline import rerank_select

        @dataclass
        class _C:
            chunk_id: str
            level: str
            text: str
            span_ids: list
            page_start: int
            page_end: int
            parent_id: str | None = None
            kinds: list = field(default_factory=list)

        child = _C("c1", "child", "cocuk metni", ["d#1.0"], 1, 1, parent_id="p1")
        parent = _C("p1", "parent", "parent metni", ["d#1.0", "d#2.0"], 1, 2)
        by_id = {"c1": child}
        if include_parents:
            by_id["p1"] = parent

        class _R:
            def rerank(self, q, pairs):
                return [(cid, 0.9) for cid, _t in pairs]

        return rerank_select("soru", [("c1", 1.0)], by_id, _R(), top_n=1)

    def test_parent_text_absent_when_parents_excluded(self):
        ctxs = self._fixture(include_parents=False)
        self.assertEqual(len(ctxs), 1)
        self.assertIsNone(ctxs[0].parent_text)

    def test_parent_text_present_when_parents_included(self):
        ctxs = self._fixture(include_parents=True)
        self.assertEqual(len(ctxs), 1)
        self.assertEqual(ctxs[0].parent_text, "parent metni")


if __name__ == "__main__":
    unittest.main()
