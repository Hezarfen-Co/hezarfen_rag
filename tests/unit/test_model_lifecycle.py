"""#80 (EXP-010/OPS-07) — model yaşam döngüsü: yükleme yarışı + sürüm pinleme.

KOŞULARAK KANITLANDI: `_load` kontrol-sonra-ata desenindeydi ve **hiç kilit
yoktu**. FastAPI uç noktaları `def` (sync) olduğu için Starlette bunları anyio
worker havuzunda (varsayılan 40) **gerçekten paralel** koşturuyor.

Gerçek sınıfla ölçüldü: **8 thread → 8 model yüklemesi** (1 olmalıydı).

Başarısızlık: soğuk servise 8 öğrenci aynı anda sorarsa BGE-M3 (+reranker)
8 kez paralel yüklenir → 8 paralel `snapshot_download` (~2,3 GB × 2 model)
ve/veya 8 kopya ağırlık RAM'de → **OOM-kill**. Hayatta kalsa bile yalnız son
atanan örnek kullanılır.
"""
import sys
import threading
import time
import unittest
from unittest import mock

from src.embed.embedder import BGEM3Embedder
from src.rerank.reranker import BGEReranker


class _Sayac:
    """Model yükleyicisinin yerine geçer; kaç kez çağrıldığını sayar."""

    def __init__(self, gecikme=0.05):
        self.n = 0
        self.gecikme = gecikme
        self._lock = threading.Lock()

    def __call__(self, *a, **kw):
        with self._lock:
            self.n += 1
        time.sleep(self.gecikme)          # yükleme zaman alır → yarış penceresi
        return object()


class LoadRaceTests(unittest.TestCase):
    def _kos(self, nesne, n_thread=8):
        """`_build_model` yamalanır — `sys.modules` DEĞİL.

        İlk sürümde `sys.modules["FlagEmbedding"]` yamalanıyordu; bu torch'un
        C uzantı importunu bozup `SystemError: bad call flags` üretiyordu ve
        testler ayrı ayrı geçip BİRLİKTE düşüyordu. Ağır yükleme ayrı bir
        metoda alındı; eşzamanlılık sözleşmesi artık torch'a hiç dokunmadan
        sınanıyor."""
        sayac = _Sayac()
        hatalar = []

        def hedef():
            try:
                nesne._load()
            except Exception as e:                   # noqa: BLE001
                hatalar.append(repr(e))

        with mock.patch.object(type(nesne), "_build_model", lambda self: sayac()):
            ths = [threading.Thread(target=hedef) for _ in range(n_thread)]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
        self.assertEqual(hatalar, [], "yükleme sırasında istisna")
        return sayac.n

    def test_embedder_loads_exactly_once_under_concurrency(self):
        n = self._kos(BGEM3Embedder())
        self.assertEqual(n, 1, f"model {n} kez yüklendi (yarış geri geldi)")

    def test_reranker_loads_exactly_once_under_concurrency(self):
        n = self._kos(BGEReranker())
        self.assertEqual(n, 1, f"reranker {n} kez yüklendi")

    def test_heavy_import_lives_behind_a_seam(self):
        """`_build_model` ayrı olmalı: yoksa eşzamanlılık sözleşmesi ancak
        torch yüklenerek test edilebilir ve test kırılgan olur."""
        for sinif in (BGEM3Embedder, BGEReranker):
            with self.subTest(sinif.__name__):
                self.assertTrue(hasattr(sinif, "_build_model"))

    def test_fast_path_does_not_take_the_lock(self):
        """Model yüklüyken kilide girmek her çağrıya gereksiz serileşme ekler."""
        e = BGEM3Embedder()
        e._model = object()
        e._load_lock = None               # kilide girilirse AttributeError
        self.assertIsNotNone(e._load())

    def test_both_classes_have_a_warmup_hook(self):
        """Modeli AÇILIŞTA yüklemek ilk isteği bekletmemek için."""
        for sinif in (BGEM3Embedder, BGEReranker):
            with self.subTest(sinif.__name__):
                self.assertTrue(hasattr(sinif, "warmup"))


class RevisionPinTests(unittest.TestCase):
    """`snapshot_download`'a `revision` verilmiyordu.

    Verilmediğinde her indirme depo HEAD'ini alır; yayıncı ağırlığı
    güncellerse **uygulama sessizce başka bir modele geçer** ve ölçülmüş bütün
    sayılar (kapı değerleri dahil) o modele ait olmaktan çıkar.
    """

    def test_revision_is_passed_through(self):
        from src.embed import embedder as E
        cagrilar = {}

        def sahte_snapshot(model, **kw):
            cagrilar.update(kw)
            return "/tmp/model"

        e = BGEM3Embedder()
        with mock.patch.object(E, "MODEL_REVISION", "abc123"), \
             mock.patch.dict(sys.modules, {"huggingface_hub": mock.MagicMock(
                 snapshot_download=sahte_snapshot)}):
            e._resolve_model_path()
        self.assertEqual(cagrilar.get("revision"), "abc123")

    def test_local_dir_skips_download(self):
        import os
        import tempfile
        d = tempfile.mkdtemp()
        e = BGEM3Embedder(model_name=d)
        self.assertEqual(e._resolve_model_path(), d)
        self.assertTrue(os.path.isdir(d))

    def test_default_is_unpinned_and_documented(self):
        """Varsayılan `None` = eski davranış. Üretimde bir sha verilmeli;
        bu test kararın BİLİNÇLİ olduğunu kayda geçirir."""
        from src.embed.embedder import MODEL_REVISION as A
        from src.rerank.reranker import MODEL_REVISION as B
        self.assertIsNone(A)
        self.assertIsNone(B)
        import inspect
        from src.embed import embedder
        self.assertIn("PINLENEBILIR", inspect.getsource(embedder))


if __name__ == "__main__":
    unittest.main()
