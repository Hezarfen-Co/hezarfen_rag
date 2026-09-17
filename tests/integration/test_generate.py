"""Faz 1.7a entegrasyon — 12-bio üzerinde GERÇEK DeepSeek çağrısı ile kaynak-sınırlı
üretim + atıf (kaynak yer bulma).

Kapsam-içi soru → gerçek sayfa numaralı atıf + gerçek maliyet ($) doğrulanır.
Kapsam-dışı soru → FAIL-CLOSED (LLM hiç çağrılmadan çekimser dönüş) doğrulanır.
Model/anahtar/veri yoksa ATLANIR (CI'da patlamaz).

Maliyet defteri (costlog): bu test GERÇEK Obsidian ledger'ına (`C:/Users/w/
Documents/Hezarfen/rag/runs.jsonl`) YAZMAZ — Generator'a `costlog.record`'un
`ledger=`/`maliyet=` parametrelerini geçici bir dizine yönlendiren bir
`cost_recorder` enjekte edilir. Testte hem temp ledger'ın gerçekten kullanıldığı
HEM DE gerçek ledger'ın değişmediği doğrulanır (bkz. test_zz_* aşağıda).

.env: `LLM_API_KEY` .env dosyasından `os.environ`'a yüklenir (zaten set
değilse); DEĞER ASLA LOGLANMAZ/YAZDIRILMAZ.
"""
from __future__ import annotations

import functools
import os
import sys
import tempfile
import unittest

import corpus

from src import costlog


def _load_dotenv(path: str = ".env") -> None:
    """`.env`'deki KEY=VALUE satırlarını os.environ'a yükler (üzerine yazmaz).
    Değerler asla stdout/log'a yazılmaz."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_dotenv()

BOOK = corpus.book_path()

# GERÇEK Obsidian ledger'ı — bu test dosyasının ASLA yazmaması gereken dosya.
# Testler bunun içeriğini _prepare() çağrılmadan ÖNCE anlık görüntüler, sonunda
# değişmediğini doğrular (bkz. GenerateIntegrationTests.test_zz_*).
_REAL_LEDGER_SNAPSHOT_PATH = costlog.LEDGER


def _snapshot_real_ledger() -> bytes | None:
    if os.path.exists(_REAL_LEDGER_SNAPSHOT_PATH):
        with open(_REAL_LEDGER_SNAPSHOT_PATH, "rb") as f:
            return f.read()
    return None


# _prepare() (ağır model yükleme + gerçek API) çalışmadan ÖNCE al — böylece
# _prepare() içindeki hiçbir şey (hatta hata durumları) bu anlık görüntüyü kirletmez.
_REAL_LEDGER_BEFORE = _snapshot_real_ledger()

_TMP_DIR = tempfile.mkdtemp(prefix="hezarfen_test_generate_ledger_")
_TMP_LEDGER = os.path.join(_TMP_DIR, "runs.jsonl")
_TMP_MALIYET = os.path.join(_TMP_DIR, "Maliyet.md")


class _CountingLLMClient:
    """Gerçek DeepSeek'i sarar; FAIL-CLOSED yolunda LLM'in HİÇ çağrılmadığını
    doğrulamak için çağrı sayacı tutar (davranışı gerçek API ile değiştirmez)."""
    def __init__(self, real):
        self._real = real
        self.calls = 0

    def chat(self, *args, **kwargs):
        self.calls += 1
        return self._real.chat(*args, **kwargs)


# _prepare() içinde SKIP edilmesi gereken durumlar: model/veri/bağımlılık yok.
# Başka her exception (gerçek kod hatası — AttributeError, TypeError, vb.)
# YÜKSELMELİ ki test FAIL etsin; sessizce SKIP'e çevrilmesin.
_SKIP_EXCEPTIONS = (ImportError, ModuleNotFoundError, FileNotFoundError, OSError)


def _prepare():
    if not os.environ.get("LLM_API_KEY"):
        return None
    try:
        from src.ingest.canonical import build_canonical
        from src.chunk import chunk_document
        from src.embed import BGEM3Embedder
        from src.index import DenseIndex, BM25Index
        from src.retrieve import SparseIndex, HybridRetriever
        from src.rerank import BGEReranker
        from src.providers.llm import LLMClient
        from src.generate import Generator, build_span_meta

        doc = build_canonical(BOOK, sinif=corpus.find_book()[1], ders=corpus.find_book()[2])
        chunks = chunk_document(doc)
        children = [c for c in chunks if c.level == "child"]
        chunks_by_id = {c.chunk_id: c for c in chunks}      # child + parent
        span_meta = build_span_meta(doc)

        emb = corpus.shared_embedder()
        ids, vecs = emb.embed_chunks(children, batch_size=16)
        texts = [c.text for c in children]
        sparse_docs = emb.embed_sparse(texts, batch_size=16)
        dense = DenseIndex(dim=1024).build(ids, vecs)
        bm25 = BM25Index().build(ids, texts)
        sparse = SparseIndex().build(ids, sparse_docs)
        retr = HybridRetriever(emb, dense, bm25, sparse)

        rr = corpus.shared_reranker()
        rr.rerank("ısınma", [("x", "deneme metni")])         # modeli yükle

        counting_ds = _CountingLLMClient(LLMClient())
        # GERÇEK Obsidian ledger'ına DOKUNMA: costlog.record'u geçici dosyalara
        # yönlendiren bir cost_recorder enjekte et (bulgu #3).
        cost_recorder = functools.partial(costlog.record, ledger=_TMP_LEDGER,
                                          maliyet=_TMP_MALIYET)
        gen = Generator(retr, rr, chunks_by_id, span_meta, counting_ds,
                        ders="biyoloji", abstain_score=0.30, module="chat",
                        cost_recorder=cost_recorder)
        return gen, counting_ds
    except _SKIP_EXCEPTIONS as e:
        print(f"[test_generate] _prepare() SKIP ({type(e).__name__}): {e}",
             file=sys.stderr)
        return None
    # NOT: başka Exception türleri kasıtlı olarak YAKALANMIYOR — gerçek kod
    # hataları burada SESSİZCE SKIP'e çevrilmemeli, test/modül yüklemesi FAIL etmeli.


_PREP = _prepare() if os.path.exists(BOOK) else None


@unittest.skipUnless(_PREP is not None,
                     "korpus / LLM_API_KEY / BGE modelleri yok")
class GenerateIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gen, cls.llm = _PREP
        # SORGU KORPUSTAN TÜRETİLİR (aynı gerekçe: test_rerank).
        en_uzun = max(cls.gen.chunks_by_id.values(), key=lambda c: len(c.text))
        cls.QUERY = " ".join(en_uzun.text.split()[:20])

    def test_in_scope_question_returns_grounded_citation(self):
        result = self.gen.answer(self.QUERY)

        self.assertFalse(result.abstained, f"beklenmedik çekimser: {result.reason}")
        self.assertGreaterEqual(len(result.citations), 1)
        for c in result.citations:
            self.assertTrue(c["pages"], f"atıfta sayfa yok: {c}")
            for p in c["pages"]:
                self.assertGreater(p, 0)
            self.assertTrue(c["chunk_id"] in self.gen.chunks_by_id)
        self.assertRegex(result.text, r"\[\d+\]")
        self.assertGreater(result.cost_usd, 0.0)
        self.assertIsNotNone(result.usage)
        self.assertGreater(result.usage.output, 0)

        print(f"\n[test_generate] soru={self.QUERY[:50]!r}\n"
              f"  cevap: {result.text}\n"
              f"  atıflar: {result.citations}\n"
              f"  maliyet: ${result.cost_usd:.6f} · gecikme: {result.latency_s:.2f}s")

    def test_out_of_scope_question_abstains_without_llm_call(self):
        calls_before = self.llm.calls
        result = self.gen.answer("Bugün hava nasıl?")

        self.assertTrue(result.abstained,
                        f"kapsam-dışı soru çekimser dönmedi: {result.text!r}")
        self.assertEqual(result.reason, "insufficient_data")
        self.assertEqual(result.text, "Kaynaklarda bu bilgi bulunamadı.")
        self.assertEqual(result.cost_usd, 0.0)
        self.assertEqual(self.llm.calls, calls_before, "LLM çağrılmamalıydı")

        print(f"\n[test_generate] kapsam-disi soru - abstained={result.abstained}, "
              f"reason={result.reason}, llm_calls_delta=0")

    def test_zz_cost_recorder_wrote_to_temp_ledger_real_ledger_untouched(self):
        """DOĞRULAYICI bulgusu #3: test_in_scope_question_returns_grounded_citation
        gerçek bir DeepSeek çağrısı + costlog.record tetikledi. Bu test (adı 'zz'
        ile alfabetik SONRA çalışır) hem enjekte edilen cost_recorder'ın gerçekten
        TEMP ledger'a yazdığını HEM DE gerçek Obsidian ledger'ının
        (C:/Users/w/Documents/Hezarfen/rag/runs.jsonl) HİÇ değişmediğini kanıtlar."""
        self.assertTrue(os.path.exists(_TMP_LEDGER),
                        "cost_recorder temp ledger'a hiç yazmadı")
        with open(_TMP_LEDGER, encoding="utf-8") as f:
            temp_lines = [ln for ln in f if ln.strip()]
        self.assertGreaterEqual(len(temp_lines), 1,
                                "temp ledger'da hiç run kaydı yok")

        real_after = _snapshot_real_ledger()
        self.assertEqual(real_after, _REAL_LEDGER_BEFORE,
                         "GERÇEK Obsidian ledger'ı (runs.jsonl) DEĞİŞTİ — "
                         "temp-ledger izolasyonu bozuk!")

        print(f"\n[test_generate] temp ledger: {_TMP_LEDGER} ({len(temp_lines)} run) · "
              f"gerçek ledger değişmedi: {_REAL_LEDGER_SNAPSHOT_PATH}")


if __name__ == "__main__":
    unittest.main()
