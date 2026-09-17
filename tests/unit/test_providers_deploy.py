"""DEPLOY VARS SAYILANI + KAPASİTE ZARFI (API sağlayıcı yolu).

İki sözleşmeyi sabitler:

1. SAĞLAYICI ÖN DENETİMİ (`src/service/preflight.py`): seçilen sağlayıcının
   taban adresi/modeli/anahtarı eksikse servis AÇILIŞTA reddeder. Ölçülen
   sınıf: eksik anahtarla ayağa kalkan konteyner /health ve /ready'de YEŞİL
   kalıyor, yalnız ilk gerçek soru düşüyordu — yani deploy kapısı geçiyor,
   ürün ölü oluyordu.

2. ZARF (envelope) TEK KAYNAK: compose.yaml'daki `x-rag-envelope` bloğu hem
   konteyner `mem_limit`'ini hem CI kapasite eşiğini besler; README ve
   PROJECT_STATE aynı sayıları yayınlar. Sayıyı ikinci kez yazmak, model
   çağından kalma 12 GB / 20 GB eşiğinin sessizce geri gelmesi demekti.

ÖLÇÜM (2026-09-17, PROJECT_STATE §11.2): API gömme + API rerank ile yerel
modeller hiç indirilmez; torch import ~0,4 GB + 0,53 GB/10k chunk → tek korpus
≈1,1 GB, 3×10k chunk ≈2,6 GB.
"""
import contextlib
import io
import os
import re
import unittest
from unittest import mock

from src.embed import provider as embed_provider
from src.rerank import provider as rerank_provider
from src.service import preflight

_KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Zarfın yayınlanmış değerleri (tek kaynak: compose.yaml).
_MEM_LIMIT_MB = 3072
_DISK_MIN_GB = 8


def _oku(ad: str) -> str:
    with open(os.path.join(_KOK, ad), encoding="utf-8") as fh:
        return fh.read()


def _tam_api_env(**ek):
    env = {"RAG_EMBED_API_BASE": "https://ornek/v1",
           "RAG_EMBED_MODEL": "embed-1",
           "RAG_EMBED_API_KEY": "e-anahtar",
           "RAG_RERANK_API_URL": "https://ornek/rerank",
           "RAG_RERANK_MODEL": "rerank-1",
           "RAG_RERANK_API_KEY": "r-anahtar",
           "RAG_ALLOW_UNCALIBRATED_ABSTAIN": "1",
           "LLM_API_KEY": "llm-anahtar"}
    env.update(ek)
    return env


@contextlib.contextmanager
def _saglayicilar(embed: str = "api", rerank: str = "api",
                  allow_uncalibrated: bool = True):
    """SEÇİMİ modül sabitlerinden sürer — çalışma zamanının okuduğu yer.

    `RAG_ALLOW_UNCALIBRATED_ABSTAIN` de modül sabitidir (import anında donar);
    gerçek açılışta ortamla AYNI kaynaktan gelir, testte açıkça verilir.
    """
    with mock.patch.object(embed_provider, "PROVIDER", embed), \
         mock.patch.object(rerank_provider, "PROVIDER", rerank), \
         mock.patch.object(rerank_provider, "ALLOW_UNCALIBRATED",
                           allow_uncalibrated):
        yield


class ProviderConfigTests(unittest.TestCase):
    def test_local_selection_needs_no_api_config(self):
        """Yerel yol (ölçülmüş kalite) anahtar istemez: regresyon kapısı."""
        with _saglayicilar("local", "local"):
            self.assertEqual(preflight.check_provider_config({"LLM_API_KEY": "k"}),
                             [])

    def test_api_selection_names_every_missing_key(self):
        with _saglayicilar():
            eksik = preflight.check_provider_config({})
        metin = "\n".join(eksik)
        for ad in ("RAG_EMBED_API_BASE", "RAG_EMBED_MODEL", "RAG_EMBED_API_KEY",
                   "RAG_RERANK_API_URL", "RAG_RERANK_MODEL",
                   "RAG_RERANK_API_KEY", "LLM_API_KEY"):
            self.assertIn(ad, metin, f"{ad} adıyla söylenmeli")

    def test_api_complete_config_passes(self):
        with _saglayicilar():
            self.assertEqual(preflight.check_provider_config(_tam_api_env()), [])

    def test_cohere_selection_needs_the_same_three_names(self):
        """`cohere` native `/v2/embed` yoludur ama yapılandırma yüzeyi AYNI:
        taban adres + model + anahtar. Denetim onu tanımazsa servis açılışta
        "tanınmıyor" diye reddederdi — oysa yol gerçek."""
        with _saglayicilar("cohere", "api"):
            eksik = preflight.check_provider_config({})
        metin = "\n".join(eksik)
        for ad in ("RAG_EMBED_API_BASE", "RAG_EMBED_MODEL", "RAG_EMBED_API_KEY"):
            self.assertIn(ad, metin, f"{ad} adıyla söylenmeli")

    def test_cohere_complete_config_passes(self):
        with _saglayicilar("cohere", "api"):
            self.assertEqual(preflight.check_provider_config(_tam_api_env()), [])

    def test_voyage_selection_is_accepted_with_the_same_three_names(self):
        """Sahadaki seçim: `RAG_EMBED_PROVIDER=voyage` (OpenAI biçimli
        /v1/embeddings, üstelik `input_type` sözlüğü ayrı). Denetim onu
        tanımazsa servis açılışta reddederdi — oysa yol gerçek ve canlı."""
        with _saglayicilar("voyage", "api"):
            eksik = preflight.check_provider_config({})
        metin = "\n".join(eksik)
        for ad in ("RAG_EMBED_API_BASE", "RAG_EMBED_MODEL", "RAG_EMBED_API_KEY"):
            self.assertIn(ad, metin, f"{ad} adıyla söylenmeli")

    def test_voyage_complete_config_passes(self):
        with _saglayicilar("voyage", "api"):
            self.assertEqual(preflight.check_provider_config(_tam_api_env()), [])

    def test_cohere_key_can_come_through_env_name_indirection(self):
        """Sahadaki gerçek biçim: `RAG_EMBED_API_KEY_ENV=RAG_EMBED_API_KEY`."""
        ortam = _tam_api_env()
        ortam.pop("RAG_EMBED_API_KEY")
        with _saglayicilar("cohere", "api"):
            with mock.patch.object(embed_provider, "API_KEY_ENV",
                                   "RAG_EMBED_API_KEY"):
                self.assertEqual(
                    preflight.check_provider_config(
                        {**ortam, "RAG_EMBED_API_KEY": "deger"}), [])

    def test_key_can_come_through_env_name_indirection(self):
        """Kodun GERÇEK mekanizması: `*_API_KEY_ENV=<DEĞİŞKEN>`."""
        ortam = _tam_api_env()
        ortam.pop("RAG_EMBED_API_KEY")
        ortam["PAYLASILAN_ANAHTAR"] = "deger"
        with _saglayicilar():
            with mock.patch.object(embed_provider, "API_KEY_ENV",
                                   "PAYLASILAN_ANAHTAR"):
                self.assertEqual(preflight.check_provider_config(ortam), [])
            with mock.patch.object(embed_provider, "API_KEY_ENV",
                                   "BASKA_ANAHTAR"):
                eksik = preflight.check_provider_config(ortam)
        self.assertIn("BASKA_ANAHTAR", "\n".join(eksik),
                      "dolaylı ad eksikse OKUNAN ad söylenmeli")

    def test_unknown_provider_spelling_is_reported(self):
        with _saglayicilar("magic", "local"):
            eksik = preflight.check_provider_config({"LLM_API_KEY": "k"})
        self.assertIn("tanınmıyor", "\n".join(eksik))

    def test_uncalibrated_rerank_requires_explicit_flag(self):
        """API rerank skorları çekimserlik eşiği için kalibre DEĞİL; sessizce
        devre dışı kalan fail-closed kapı, hiç olmayandan tehlikelidir."""
        ortam = _tam_api_env()
        ortam.pop("RAG_ALLOW_UNCALIBRATED_ABSTAIN")
        with _saglayicilar(), \
             mock.patch.object(preflight, "ABSTAIN_SCORE_DEFAULT", 0.30), \
             mock.patch.object(rerank_provider, "ALLOW_UNCALIBRATED", False):
            eksik = preflight.check_provider_config(ortam)
        self.assertIn("RAG_ALLOW_UNCALIBRATED_ABSTAIN", "\n".join(eksik))

    def test_disabled_abstain_gate_removes_the_complaint(self):
        ortam = _tam_api_env()
        ortam.pop("RAG_ALLOW_UNCALIBRATED_ABSTAIN")
        with _saglayicilar(), \
             mock.patch.object(preflight, "ABSTAIN_SCORE_DEFAULT", 0.0):
            self.assertEqual(preflight.check_provider_config(ortam), [])

    def test_enforce_refuses_with_a_named_report(self):
        err = io.StringIO()
        with _saglayicilar():
            with contextlib.redirect_stderr(err), \
                 self.assertRaises(SystemExit) as ctx:
                preflight.enforce({})
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("RAG_EMBED_API_KEY", err.getvalue())

    def test_validate_cli_exit_codes(self):
        with _saglayicilar():
            with mock.patch.object(preflight, "check_provider_config",
                                   return_value=["X boş"]):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    kod = preflight.main(["--validate"])
        self.assertEqual(kod, 2)
        self.assertIn("X boş", err.getvalue())
        with _saglayicilar(), \
             mock.patch.object(preflight, "check_provider_config",
                               return_value=[]):
            self.assertEqual(preflight.main(["--validate"]), 0)


class DeploySurfaceTests(unittest.TestCase):
    """Zarf + varsayılanlar: dört dosya aynı şeyi söylemeli."""

    def test_envelope_is_the_single_source(self):
        compose = _oku("compose.yaml")
        blok = re.search(r"^x-rag-envelope:\n((?:[ \t]+.*\n)+)", compose,
                         re.M)
        self.assertIsNotNone(blok, "x-rag-envelope bloğu yok")
        deger = dict(re.findall(r"^\s+(\w+):\s*(\d+)\s*$", blok.group(1), re.M))
        self.assertEqual(int(deger["mem_limit_mb"]), _MEM_LIMIT_MB)
        self.assertEqual(int(deger["disk_min_gb"]), _DISK_MIN_GB)
        # Ürün servisinin tavanı zarfın BAYT karşılığı olmalı (3g = 2,86 GiB
        # tuzağı: ondalık `g` ölçülen zarfın üstünde neredeyse baş bırakmaz).
        servis = compose.split("  rag:\n", 1)[1].split("  # #96", 1)[0]
        self.assertIn(f"mem_limit: {_MEM_LIMIT_MB * 1024 * 1024}", servis)

    def test_workflow_reads_the_envelope_instead_of_hardcoding(self):
        yml = _oku(".github/workflows/main.yml")
        self.assertIn("x-rag-envelope", yml, "CI eşiği zarfı okumalı")
        self.assertIn('"$mem_limit_mb"', yml)
        self.assertIn('"$disk_min_gb"', yml)
        for eski in ("-lt 12000", "-lt 20 ", "need >= 12000", "need >= 20)"):
            self.assertNotIn(eski, yml, f"eski eşik kalmış: {eski}")

    def test_docs_publish_the_envelope(self):
        for ad in ("README.md", "PROJECT_STATE.md"):
            metin = _oku(ad)
            self.assertIn(str(_MEM_LIMIT_MB), metin, f"{ad}: RAM tavanı")
            self.assertIn(f"{_DISK_MIN_GB} GB", metin, f"{ad}: disk eşiği")

    def test_deploy_provider_defaults_are_api_in_every_surface(self):
        ckok = preflight.DEPLOY_DEFAULT_PROVIDERS
        self.assertEqual(ckok, {"RAG_EMBED_PROVIDER": "api",
                                "RAG_RERANK_PROVIDER": "api"})
        yuzeyler = {
            "Containerfile": _oku("Containerfile"),
            ".env.example": _oku(".env.example"),
            "deploy/hezarfen_rag.env.example":
                _oku("deploy/hezarfen_rag.env.example"),
        }
        for ad, metin in yuzeyler.items():
            for anahtar, beklenen in ckok.items():
                # Containerfile'da satırlar `ENV ... \` bloğunun içindedir.
                self.assertRegex(
                    metin, rf"(?m)^[ \t]*{anahtar}={beklenen}[ \t]*\\?[ \t]*$",
                    f"{ad}: {anahtar}={beklenen}")

    def test_local_path_stays_selectable_and_fully_documented(self):
        """API yolunu EKLEDİK, yereli SİLMEDİK: ölçülmüş kalite sayıları ve
        eval koşuları yerel yola aittir. Bu test iki şeyi sabitler: (a) yerel
        seçim hâlâ fabrikalardan doğru sınıfları döndürüyor, (b) operatör
        şablonu geri dönüş anahtarlarını AÇIKÇA yazıyor."""
        from src.embed.embedder import BGEM3Embedder
        from src.rerank.reranker import BGEReranker
        gomme = embed_provider.build_embedder(provider="local")
        self.assertIsInstance(gomme, BGEM3Embedder)
        self.assertTrue(gomme.sparse_supported, "yerel yol sparse üretir")
        rr = rerank_provider.build_reranker(provider="local")
        self.assertIsInstance(rr, BGEReranker)
        # Yerel skorlar kalibre SAYILIR (sabit yok = kalibre); eşik kapısı
        # yerel sağlayıcıda sorun çıkarmamalı.
        with mock.patch.object(rerank_provider, "ALLOW_UNCALIBRATED", False):
            rerank_provider.check_abstain_compatibility(rr, abstain_score=0.30)
        sablon = _oku("deploy/hezarfen_rag.env.example")
        self.assertIn("RAG_EMBED_PROVIDER=local", sablon)
        self.assertIn("RAG_RERANK_PROVIDER=local", sablon)

    def test_operator_env_example_is_systemd_safe_and_complete(self):
        """Satır-İÇİ `#` yasak: systemd `EnvironmentFile=` onu DEĞERİN PARÇASI
        yapar (ölçüldü) ve sağlayıcı seçimi bozulur."""
        metin = _oku("deploy/hezarfen_rag.env.example")
        for satir in metin.splitlines():
            if satir.lstrip().startswith("#") or not satir.strip():
                continue
            self.assertRegex(satir, r"^[A-Za-z_][A-Za-z0-9_]*=[^\s#]*$",
                             f"düz KEY=value değil: {satir!r}")
        zorunlu = ("RAG_EMBED_PROVIDER", "RAG_EMBED_API_BASE", "RAG_EMBED_MODEL",
                   "RAG_EMBED_API_KEY", "RAG_EMBED_API_KEY_ENV",
                   "RAG_RERANK_PROVIDER", "RAG_RERANK_API_URL",
                   "RAG_RERANK_MODEL", "RAG_RERANK_API_KEY",
                   "RAG_RERANK_API_KEY_ENV", "RAG_ALLOW_UNCALIBRATED_ABSTAIN",
                   "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL",
                   "AI_SHARED_TOKEN", "HEZARFEN_NET", "HEZARFEN_DATA_VOLUME",
                   "BOOK_PATH", "SINIF", "DERS", "RAG_MAX_CORPORA")
        for ad in zorunlu:
            self.assertRegex(metin, rf"(?m)^#?{ad}=", f"şablonda {ad} yok")

    def test_operator_env_example_covers_every_refusal_the_preflight_names(self):
        """Şablon, denetimin söylediği HER adı taşımalı: eksik anahtarın
        nereye yazılacağını operatör şablondan bulabilmeli."""
        metin = _oku("deploy/hezarfen_rag.env.example")
        with _saglayicilar(), \
             mock.patch.object(preflight, "ABSTAIN_SCORE_DEFAULT", 0.30), \
             mock.patch.object(rerank_provider, "ALLOW_UNCALIBRATED", False):
            eksik = preflight.check_provider_config({})
        self.assertTrue(eksik)
        for mesaj in eksik:
            ad = re.match(r"([A-Z_][A-Z0-9_]*)", mesaj)
            self.assertIsNotNone(ad, f"mesaj adla başlamalı: {mesaj!r}")
            self.assertRegex(metin, rf"(?m)^#?{ad.group(1)}=",
                             f"{ad.group(1)} şablonda yok")


class LocalStackVolumeTests(unittest.TestCase):
    """YEREL YIĞIN ARTIK İMAJDA DEĞİL (küçük imge kararı, 2026-09-17).

    Bağımlılıklar bir podman VOLUME'undaki venv'de durur; servis onu `sys.path`e
    ekler. Volume sağlanmadıysa `local` seçimi ImportError ile değil, ADIYLA ve
    çalıştırılacak komutu söyleyerek reddedilir.
    """

    def test_local_without_any_stack_refuses_with_the_command(self):
        with _saglayicilar("local", "local"), \
             mock.patch.object(preflight, "_yerel_yigin_site_packages",
                               return_value=[]), \
             mock.patch("importlib.util.find_spec", return_value=None):
            eksik = preflight.check_provider_config({"LLM_API_KEY": "k"})
        metin = "\n".join(eksik)
        self.assertIn("provision_local_stack.sh", metin)
        self.assertIn(preflight.LOCAL_VENV_ENV, metin)
        self.assertIn(preflight.LOCAL_MODELS_ENV, metin)

    def test_local_with_provisioned_volume_passes(self):
        with _saglayicilar("local", "local"), \
             mock.patch.object(preflight, "_yerel_yigin_site_packages",
                               return_value=["/vol/venv/lib/python3.11/site-packages"]), \
             mock.patch("importlib.util.find_spec", return_value=object()):
            self.assertEqual(preflight.check_provider_config({"LLM_API_KEY": "k"}), [])

    def test_prepare_adds_the_volume_venv_to_sys_path(self):
        import sys
        with mock.patch.object(preflight, "_yerel_yigin_site_packages",
                               return_value=["/vol/venv/lib/python3.11/site-packages"]):
            preflight.yerel_yigin_hazirla({preflight.LOCAL_VENV_ENV: "/vol/venv",
                                           preflight.LOCAL_MODELS_ENV: "/vol/models"})
            self.assertEqual(sys.path[0], "/vol/venv/lib/python3.11/site-packages")
            hf_home = os.environ.get("HF_HOME")
            os.environ.pop("HF_HOME", None)          # testin izini sil
        sys.path.remove("/vol/venv/lib/python3.11/site-packages")
        self.assertEqual(hf_home, "/vol/models",
                         "ağırlıklar volume'da kalmalı (HF_HOME)")

    def test_durum_reads_the_provisioning_marker(self):
        import tempfile
        import pathlib as _p
        with tempfile.TemporaryDirectory() as d:
            (_p.Path(d) / "PROVISIONED").write_text(
                "PROVISIONED_IMAGE=localhost/hezarfen_rag:current\n"
                "PROVISIONED_TAG=abc123\nPYTHON=3.11.9\nDATE=2026-09-17T00:00:00+00:00\n",
                encoding="utf-8")
            durum = preflight.yerel_yigin_durumu(
                {preflight.LOCAL_VENV_ENV: os.path.join(d, "venv")})
        self.assertIn("tag=abc123", durum)
        self.assertIn("python=3.11.9", durum)

    def test_missing_marker_is_reported_as_missing(self):
        self.assertIn("yok", preflight.yerel_yigin_durumu({}))


class SmallImageContractTests(unittest.TestCase):
    """Varsayılan imge KÜÇÜK: ağır yığın ne imajda ne varsayılan derlemede."""

    def test_default_build_does_not_install_the_local_stack(self):
        c = _oku("Containerfile")
        self.assertIn("ARG WITH_LOCAL_MODELS=0", c)
        kapi = c.index('if [ "$WITH_LOCAL_MODELS" = "1" ]')
        self.assertGreater(c.index("requirements-local.txt", kapi), kapi,
                           "yerel liste yalnız kapının İÇİNDE kurulmalı")
        # Yorumları at: başlıkta ESKİ hatalı satır anlatılıyor (test onu kod
        # sanmasın — bu tuzak repoda bir kez yaşandı, bkz. test_deployment).
        kod = "\n".join(l for l in c.splitlines()
                         if not l.lstrip().startswith("#"))
        self.assertIn('pip install --no-cache-dir "torch>=2.6" --index-url "${TORCH_INDEX}"',
                      kod)
        self.assertNotRegex(kod, r"(?m)^pip install[^\n]*torch",
                            "torch kurulumu koşulsuz olmamalı")
        self.assertGreater(kod.index('"torch>=2.6"'), kod.index('if [ "$WITH_LOCAL_MODELS" = "1" ]'))

    def test_local_deps_live_only_in_the_local_list(self):
        temel = _oku("requirements.txt")
        yerel = _oku("requirements-local.txt")
        for paket in ("torch", "FlagEmbedding"):
            self.assertNotRegex(temel, rf"(?m)^{paket}", f"{paket} temel listede")
            self.assertRegex(yerel, rf"(?m)^{paket}", f"{paket} yerel listede")
        self.assertNotRegex(temel, r"(?m)^deepeval",
                            "deepeval eval listesine taşındı")

    def test_containerfile_copies_the_local_list_into_the_image(self):
        """Sağlama betiği pip'i İMGE İÇİNDE çalıştırır; liste imgede olmalı."""
        c = _oku("Containerfile")
        self.assertIn("COPY requirements.txt requirements-local.txt", c,
                      "sağlama betiği imge İÇİNDE pip çalıştırır; liste imgede olmalı")

    def test_provisioner_runs_pip_inside_the_service_image(self):
        s = _oku("deploy/provision_local_stack.sh")
        self.assertIn("podman run --rm -v", s)
        self.assertIn("requirements-local.txt", s)
        self.assertIn("PROVISIONED", s)


if __name__ == "__main__":
    unittest.main()
