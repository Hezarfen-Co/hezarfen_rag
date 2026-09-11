"""Test ortamı koruması — İÇE AKTARMA ANINDA çalışır.

ÖLÇÜLDÜ (2026-09-11): birim testleri `costlog.record`'u gerçekten çağırıyor ve
kayıtlar **gerçek maliyet defterine** (Obsidian `rag/runs.jsonl` + `Maliyet.md`)
düşüyordu. Maliyet defteri bir ürün kaydıdır; test gürültüsü karışırsa birim
maliyet raporları bozulur.

NEDEN BURADA, `tests/__init__.py`'da DEĞİL: `unittest discover -s tests` üst
dizini `tests/` kabul ediyor ve test modüllerini `unit.test_x` olarak içe
aktarıyor — yani `tests` paketi hiç import EDİLMİYOR ve oradaki kod ÇALIŞMIYOR.
Bu dosya `test_*.py` desenine uyduğu için discover tarafından **mutlaka**
yüklenir, üstelik alfabetik olarak alt paketlerden (`e2e/`, `integration/`,
`unit/`) önce gelen bir konumdadır.
"""
import os
import tempfile
import unittest

os.environ["HEZARFEN_COST_VAULT"] = os.path.join(tempfile.gettempdir(),
                                                 "hezarfen-test-cost")
os.environ.pop("HEZARFEN_AUDIT_PATH", None)


class OrtamKorumasiTests(unittest.TestCase):
    def test_cost_vault_gercek_kasaya_bakmiyor(self):
        import importlib
        from src import costlog
        m = importlib.reload(costlog)
        self.assertNotIn("Obsidian", m.VAULT)
        self.assertNotIn("Hezarfen-Vault", m.VAULT)

    def test_audit_kapali(self):
        import importlib
        from src.guard import audit
        self.assertIsNone(importlib.reload(audit).AUDIT_PATH)
