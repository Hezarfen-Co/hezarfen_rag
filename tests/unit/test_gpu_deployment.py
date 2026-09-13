"""#96 (EXP-018) — GPU dağıtımı: sessiz CPU'ya düşüşü engelleme.

ÖLÇÜLEN DURUM (RTX 4060 Laptop, 10/biyoloji, gerçek `/rag/chat`):

    CPU: 40 adaylık rerank 95,9 s · uçtan uca ~96 s  -> kapı O-05 GEÇİLMEZ
    GPU: 40 adaylık rerank  1,9 s · p50 4,96 s       -> GEÇİLİR

torch, CUDA bulamazsa **sessizce** CPU'ya düşer. Konteynerde bu, sağlıklı
görünen ama her soruya bir buçuk dakikada cevap veren bir servis demektir.
Log'da tek satır bile yoktur; demo sırasında "ürün bozuk" diye okunur ve nedeni
görünmez.

Bu dosya üç şeyi sabitler:
  1. `RAG_REQUIRE_CUDA=1` iken GPU yoksa AÇILIŞTA hata (sessiz düşüş yok).
  2. Varsayılan KAPALI — CPU kurulumu ve GPU'suz geliştirme bozulmaz.
  3. `/ready` CUDA durumunu makine-okunur raporlar; operatör "neden bu kadar
     yavaş?" sorusunu gecikmeden değil, uçtan cevaplayabilir.
"""
import os
import unittest
from unittest import mock

from src.service import http_app


class CudaStatusTests(unittest.TestCase):
    """Teşhis fonksiyonu ÇÖKMEZ — teşhis sırasında çökmek en kötüsü."""

    def test_reports_the_required_fields(self):
        d = http_app.cuda_status()
        for alan in ("available", "device_count", "required"):
            self.assertIn(alan, d)
        self.assertIsInstance(d["available"], bool)

    def test_missing_torch_does_not_crash(self):
        with mock.patch.dict("sys.modules", {"torch": None}):
            d = http_app.cuda_status()
        self.assertFalse(d["available"])
        self.assertIn("reason", d)

    def test_broken_torch_does_not_crash(self):
        sahte = mock.MagicMock()
        sahte.cuda.is_available.side_effect = RuntimeError("driver mismatch")
        with mock.patch.dict("sys.modules", {"torch": sahte}):
            d = http_app.cuda_status()
        self.assertFalse(d["available"])
        self.assertIn("driver mismatch", d["reason"])

    def test_device_name_only_when_available(self):
        sahte = mock.MagicMock()
        sahte.cuda.is_available.return_value = False
        with mock.patch.dict("sys.modules", {"torch": sahte}):
            d = http_app.cuda_status()
        self.assertEqual(d["device_count"], 0)
        self.assertEqual(d.get("device_name", ""), "")


class RequireCudaTests(unittest.TestCase):
    def test_disabled_by_default_is_a_no_op(self):
        """CPU kurulumu meşrudur; varsayılan açık olsaydı GPU'suz her makinede
        servis açılmazdı."""
        with mock.patch.object(http_app, "REQUIRE_CUDA", False), \
             mock.patch.object(http_app, "cuda_status",
                               return_value={"available": False}):
            http_app.require_cuda_or_fail()          # hata YOK

    def test_raises_when_required_but_missing(self):
        with mock.patch.object(http_app, "REQUIRE_CUDA", True), \
             mock.patch.object(http_app, "cuda_status",
                               return_value={"available": False,
                                             "reason": "torch yok"}):
            with self.assertRaises(RuntimeError) as ctx:
                http_app.require_cuda_or_fail()
        self.assertIn("RAG_REQUIRE_CUDA", str(ctx.exception))

    def test_the_error_names_all_three_causes(self):
        """Mesaj teşhis edilebilir olmalı: üç ayrı kurulum adımından hangisi
        atlandıysa operatör onu bulabilsin."""
        with mock.patch.object(http_app, "REQUIRE_CUDA", True), \
             mock.patch.object(http_app, "cuda_status",
                               return_value={"available": False,
                                             "torch_cuda_build": None}):
            try:
                http_app.require_cuda_or_fail()
            except RuntimeError as e:
                metin = str(e)
        for ipucu in ("TORCH_INDEX", "nvidia-container-toolkit",
                      "nvidia.com/gpu=all"):
            self.assertIn(ipucu, metin, ipucu)
        self.assertIn("96 s", metin, "bedeli sayiyla soylenmeli")

    def test_passes_when_cuda_is_present(self):
        with mock.patch.object(http_app, "REQUIRE_CUDA", True), \
             mock.patch.object(http_app, "cuda_status",
                               return_value={"available": True,
                                             "device_count": 1}):
            http_app.require_cuda_or_fail()

    def test_env_parsing_accepts_common_spellings(self):
        import importlib
        for deger, beklenen in (("1", True), ("true", True), ("TRUE", True),
                                ("yes", True), ("on", True), ("0", False),
                                ("", False), ("hayir", False)):
            with self.subTest(deger=deger):
                with mock.patch.dict(os.environ, {"RAG_REQUIRE_CUDA": deger}):
                    mod = importlib.reload(http_app)
                    self.assertEqual(mod.REQUIRE_CUDA, beklenen)
        # Ortam eski hâline döndükten SONRA yeniden yükle, yoksa son değer sızar.
        importlib.reload(http_app)


class BuildServiceGuardTests(unittest.TestCase):
    """Kontrol AĞIR İŞTEN ÖNCE olmalı: 2,3 GB model indirip sonra patlamak,
    operatörün 5 dakikasını çöpe atar."""

    def test_build_service_checks_before_loading_models(self):
        import inspect
        kaynak = inspect.getsource(http_app.build_service)
        kontrol = kaynak.index("require_cuda_or_fail()")
        for agir in ("build_canonical(", "BGEM3Embedder(", "BGEReranker("):
            self.assertLess(kontrol, kaynak.index(agir),
                            f"CUDA kontrolu {agir} sonrasinda")


class ConfigWarningTests(unittest.TestCase):
    def test_cpu_without_require_flag_warns_with_numbers(self):
        """Uyarı, hata değil: CPU kurulumu meşrudur ama gecikmesi ölçüldü ve
        operatöre sayıyla söylenmeli."""
        with mock.patch.object(http_app, "REQUIRE_CUDA", False), \
             mock.patch.object(http_app, "cuda_status",
                               return_value={"available": False}):
            uyarilar = " ".join(http_app._yapilandirma_uyarilari())
        self.assertIn("CUDA yok", uyarilar)
        self.assertIn("96 s", uyarilar)

    def test_no_cuda_warning_when_gpu_is_present(self):
        with mock.patch.object(http_app, "REQUIRE_CUDA", False), \
             mock.patch.object(http_app, "cuda_status",
                               return_value={"available": True}):
            uyarilar = " ".join(http_app._yapilandirma_uyarilari())
        self.assertNotIn("CUDA yok", uyarilar)


class ReadyEndpointTests(unittest.TestCase):
    def test_ready_reports_cuda(self):
        from fastapi.testclient import TestClient

        class _Svc:
            generator = object()
            doc = None
            question_gen = None

        c = TestClient(http_app.create_app(_Svc()))
        d = c.get("/ready").json()
        self.assertIn("cuda", d)
        self.assertIn("available", d["cuda"])


if __name__ == "__main__":
    unittest.main()
