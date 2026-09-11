"""#49 — KVKK: öğrenci metni ve özel nitelikli çıkarım loglardan çıkarıldı.

NEDEN (EXP-010/SEC-10 + OPS-04):
- `memory/history_rewrite.py` `note=f"history-rewrite: '{query[:30]}' -> ..."`
  ile **öğrencinin yazdığı metni** `runs.jsonl`'a ve oradan `Maliyet.md`
  tablosuna **düz metin** olarak yazıyordu.
- `guard/llm_classifier.py` `cat=self_harm` yazıyordu → reşit olmayan bir
  kişiye ait **özel nitelikli (sağlık) veri çıkarımı**, zaman damgasıyla,
  şifresiz ve genel erişimli bir dosyada (KVKK m.6 + veri minimizasyonu).
- `costlog.VAULT` sabit bir **Windows** yoluydu (`C:/Users/w/...`), env override
  yoktu → Linux'ta çalışma dizininde gerçekten `./C:/Users/w/...` klasörü
  oluşuyordu (ölçüldü) ve `.gitignore`'da karşılığı olmadığı için **PII repoya
  sızabiliyordu**.

Çözüm kaydı silmek değil AYIRMAK: güvenlik olayları erişimi kısıtlı, saklama
süreli ayrı bir dosyaya; maliyet defterinde yalnız sayısal telemetri.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from src.guard import audit


class CostLedgerHasNoUserTextTests(unittest.TestCase):
    def test_history_rewrite_note_carries_no_query_text(self):
        from src.memory.history_rewrite import HistoryAwareRewriter
        notes = []

        class _P:
            _api_key = "x"

            def chat(self, prompt, system=None, **kw):
                from src.pricing import Usage
                from src.providers.deepseek import ChatResult
                return ChatResult(text="Bağımsız soru", usage=Usage(), model="stub")

        r = HistoryAwareRewriter(_P(), cost_recorder=lambda **kw: notes.append(kw))
        gizli = "Ben çok kötüyüm ve kendime zarar vermek istiyorum"
        r.rewrite([{"role": "user", "content": "önceki"}], gizli)

        self.assertTrue(notes)
        note = notes[0]["note"]
        self.assertNotIn("kötüyüm", note)
        self.assertNotIn("zarar", note)
        self.assertNotIn(gizli[:20], note)
        # teşhis için gereken şey DURUYOR
        self.assertIn("q_len=", note)
        self.assertIn("q_hash=", note)

    def test_safety_category_not_written_to_cost_ledger(self):
        from src.guard.llm_classifier import LLMSafetyClassifier
        notes = []

        class _P:
            _api_key = "x"

            def chat(self, *a, **kw):
                from src.pricing import Usage
                from src.providers.deepseek import ChatResult
                return ChatResult(text='{"safe": false, "category": "self_harm"}',
                                  usage=Usage(), model="stub")

        c = LLMSafetyClassifier(_P(), cost_recorder=lambda **kw: notes.append(kw))
        c.classify("gizli bir soru")
        self.assertTrue(notes)
        self.assertNotIn("self_harm", notes[0]["note"])

    def test_cost_vault_is_configurable_and_not_windows(self):
        import importlib
        from src import costlog
        self.assertNotIn("C:/Users", costlog.VAULT)
        with mock.patch.dict(os.environ, {"HEZARFEN_COST_VAULT": "/tmp/hz-test"}):
            m = importlib.reload(costlog)
            try:
                self.assertEqual(m.VAULT, "/tmp/hz-test")
            finally:
                importlib.reload(costlog)

    def test_gitignore_blocks_the_ledger(self):
        with open(".gitignore", encoding="utf-8") as fh:
            ig = fh.read()
        for pat in ("runs.jsonl", ".hezarfen/", "C:/"):
            self.assertIn(pat, ig, f"{pat} .gitignore'da yok")


class SafetyAuditLogTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "sec.jsonl")

    def test_disabled_by_default(self):
        """Veri minimizasyonu: açıkça istenmediyse hiçbir şey toplanmaz."""
        with mock.patch.object(audit, "AUDIT_PATH", None):
            self.assertFalse(audit.record_safety_event(
                category="self_harm", action="refuse", layer="llm", query="x"))

    def test_records_without_query_text(self):
        gizli = "kendime zarar vermek istiyorum çünkü ..."
        audit.record_safety_event(category="self_harm", action="refuse",
                                  layer="llm", query=gizli, path=self.path)
        with open(self.path, encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn("zarar", raw)
        self.assertNotIn("çünkü", raw)
        row = json.loads(raw.strip())
        self.assertEqual(row["category"], "self_harm")
        self.assertEqual(row["q_len"], len(gizli))
        self.assertEqual(len(row["q_hash"]), 12)

    def test_no_user_identity_unless_opaque_hash_given(self):
        audit.record_safety_event(category="violence_weapons", action="refuse",
                                  layer="regex", query="q", path=self.path)
        with open(self.path, encoding="utf-8") as fh:
            row = json.loads(fh.read().strip())
        self.assertNotIn("oturum_hash", row)
        audit.record_safety_event(category="violence_weapons", action="refuse",
                                  layer="regex", query="q", path=self.path,
                                  oturum_hash="opak-deger")
        rows = audit.read_events(self.path)
        self.assertEqual(rows[-1]["oturum_hash"], "opak-deger")

    def test_file_permissions_are_owner_only(self):
        audit.record_safety_event(category="self_harm", action="refuse",
                                  layer="llm", query="x", path=self.path)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_retention_drops_old_rows(self):
        import time
        old = {"ts": time.time() - 400 * 86400, "category": "eski"}
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(old) + "\n")
        audit.record_safety_event(category="self_harm", action="refuse",
                                  layer="llm", query="x", path=self.path)
        rows = audit.read_events(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "self_harm")

    def test_corrupt_line_does_not_lose_the_log(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{bozuk\n")
        self.assertTrue(audit.record_safety_event(
            category="self_harm", action="refuse", layer="llm", query="x",
            path=self.path))
        self.assertEqual(len(audit.read_events(self.path)), 1)

    def test_failure_never_raises(self):
        """Telemetri hatası bir cevabı ASLA düşürmemeli.
        `/dev/null` bir DOSYA olduğu için altına dizin açılamaz → yazım başarısız,
        ama fonksiyon istisna fırlatmaz, False döner."""
        try:
            ok = audit.record_safety_event(
                category="x", action="refuse", layer="llm", query="q",
                path="/dev/null/alt/sec.jsonl")
        except Exception as e:                      # pragma: no cover
            self.fail(f"telemetri hatası istisna fırlattı: {e!r}")
        self.assertFalse(ok)

    def test_fingerprint_is_stable_and_opaque(self):
        a = audit.query_fingerprint("aynı soru")
        b = audit.query_fingerprint("aynı soru")
        c = audit.query_fingerprint("başka soru")
        self.assertEqual(a, b)          # tekrar tespiti mümkün
        self.assertNotEqual(a, c)
        self.assertEqual(len(a), 12)    # geri çevrilemez


class ClassifierWritesToAuditTests(unittest.TestCase):
    def test_refusal_is_recorded_allow_is_not(self):
        from src.guard.llm_classifier import LLMSafetyClassifier
        d = tempfile.mkdtemp()
        path = os.path.join(d, "sec.jsonl")

        class _Broken:
            _api_key = "x"

            def chat(self, *a, **kw):
                raise RuntimeError("429")

        with mock.patch.object(audit, "AUDIT_PATH", path):
            c = LLMSafetyClassifier(_Broken(), cost_recorder=lambda **kw: None)
            c.classify("intihar etmek istiyorum")     # refuse
            c.classify("fotosentez nedir")            # allow
        rows = audit.read_events(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "refuse")
        self.assertEqual(rows[0]["layer"], "degraded")


if __name__ == "__main__":
    unittest.main()
