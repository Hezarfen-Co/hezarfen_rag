"""#81 (EXP-010/OPS-03 + OPS-17) — dağıtım: konteyner servisi başlatmıyordu.

ÖLÇÜLEN DURUM:
* `CMD ["python","-c","import src; print('...hazir...')"]` → imge bir metin
  yazdırıp **çıkıyordu**; `uvicorn` hiç çalıştırılmıyordu. `restart:
  unless-stopped` ile birlikte bu **sonsuz restart döngüsü** demekti.
* `RUN pip install torch>=2.6 --index-url ...` → tırnaksız `>=` **kabuk
  yönlendirmesine** dönüşüyor: sürüm kısıtı hiç uygulanmıyor, `/app/=2.6` çöp
  dosyası oluşuyor, pip çıktısı build loglarında görünmüyordu.
* `EXPOSE` yok; compose'da `ports` ve `healthcheck` yok.
* `.containerignore` `data/`'yı dışlıyor ama `BOOK_PATH` varsayılanı `data/...`
  → PDF konteynerde **hiç yok**.
* `.env` servis yolunda yüklenmiyordu.

Bu testler imge KURMAZ (build ağ ister); yapılandırmanın **sözleşmesini**
sabitler — aynı hataların sessizce geri gelmesini engeller.
"""
import os
import pathlib
import re
import unittest

_KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _oku(ad):
    with open(os.path.join(_KOK, ad), encoding="utf-8") as fh:
        return fh.read()


class ContainerfileTests(unittest.TestCase):
    def setUp(self):
        self.c = _oku("Containerfile")

    def test_cmd_actually_starts_the_server(self):
        self.assertIn("uvicorn", self.c)
        self.assertIn("src.service.http_app:create_app_with_warmup", self.c)
        self.assertNotIn("hazir — RAG servis girisi", self.c)

    def test_cmd_uses_the_factory_flag(self):
        """Fabrika olmadan uvicorn modül seviyesinde `app` arar; `app = ...`
        ise her içe aktarmada ısıtma thread'i başlatırdı."""
        self.assertIn("--factory", self.c)

    @staticmethod
    def _kodsuz(metin):
        """Yorum satırlarını at — dosyada eski HATALI satır açıklama olarak
        anlatılıyor; test onu kod sanmamalı. (İlk yazımda tam bunu yaptı.)"""
        return "\n".join(l for l in metin.splitlines()
                          if not l.lstrip().startswith("#"))

    def test_pip_version_constraint_is_quoted(self):
        """Tırnaksız `>=` kabuk yönlendirmesine dönüşüyordu."""
        kod = self._kodsuz(self.c)
        self.assertIn('"torch>=2.6"', kod)
        self.assertIsNone(re.search(r"""pip install[^\n]*[^"']torch>=""", kod))

    def test_build_verifies_no_redirection_garbage(self):
        self.assertIn("test ! -e /app/=2.6", self.c)

    def test_port_is_exposed(self):
        self.assertIn("EXPOSE 8000", self.c)

    def test_runs_unprivileged(self):
        self.assertIn("USER hezarfen", self.c)

    def test_healthcheck_tool_is_installed(self):
        """Sağlık yoklaması imge İÇİNDEN çalışır; `curl` olmadan çalışmaz."""
        self.assertIn("curl", self.c)

    def test_tests_are_not_shipped_in_the_production_image(self):
        self.assertNotIn("COPY tests", self.c)


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.y = _oku("compose.yaml")

    def test_ports_are_published(self):
        self.assertIn("8000:8000", self.y)

    def test_ports_bind_to_localhost_by_default(self):
        """Dışa açmak bilinçli bir karar olmalı; varsayılan yerel."""
        self.assertIn("127.0.0.1:8000:8000", self.y)

    def test_healthcheck_exists_and_uses_liveness(self):
        self.assertIn("healthcheck", self.y)
        self.assertIn("/health", self.y)
        self.assertNotIn("/ready\"", self.y)     # readiness healthcheck OLMAZ
        self.assertIn("start_period", self.y)

    def test_data_is_mounted_because_the_image_excludes_it(self):
        self.assertIn("./data:/app/data", self.y)
        self.assertIn("data/", _oku(".containerignore"))

    def test_book_path_points_at_the_mount(self):
        """BOOK_PATH mount'un İÇİNE bakmalı. Artık interpolasyon varsayılanı
        (`${BOOK_PATH:-/app/data/...}`) olduğu için her iki biçim de kabul."""
        self.assertRegex(self.y, r"BOOK_PATH: (?:\$\{BOOK_PATH:-)?/app/data/")

    def test_book_path_points_at_data_we_actually_have(self):
        """Varsayılan `data/lise/12/...` idi ve o kitap bu depoda YOK (#92) —
        konteyner açılışta patlardı.

        BOOK_PATH artık interpolasyon varsayılanıdır (`${BOOK_PATH:-...}`);
        varsayılanın kendisi çıkarılır. Korpus repoda TUTULMAZ (gitignore +
        .containerignore; dışarıdan bağlanır), bu yüzden yol bu checkout'ta
        yoksa test ATLANIR — CI'da korpus yoktur ve kırmızı olması anlamsız
        olurdu.
        """
        m = (re.search(r"BOOK_PATH: \$\{BOOK_PATH:-(\S+?)\}", self.y)
             or re.search(r"BOOK_PATH: (\S+)", self.y))
        self.assertIsNotNone(m)
        yerel = m.group(1).replace("/app/", "")
        yol = os.path.join(_KOK, yerel)
        if not os.path.isfile(yol):
            self.skipTest(f"{yerel} bu checkout'ta yok (korpus repoda tutulmaz)")
        self.assertTrue(os.path.isfile(yol))

    def test_env_file_is_loaded(self):
        self.assertIn("env_file", self.y)

    def test_model_cache_and_cost_ledger_are_persistent(self):
        for v in ("rag-models", "rag-cost"):
            self.assertIn(v, self.y)

    def test_security_knobs_are_wired(self):
        """Güvenlik düğmeleri sessizce kablosuz kalmamalı.

        #81'de compose'un `environment:` bloğu bağlıyordu. O blok artık yalnız
        cihaza özel korpus anahtarlarını taşır: compose `environment:` daima
        kazanır, yani burada listelenen bir sır operatörün env dosyasındaki
        değeri EZERDİ (RAG_SERVICE_TOKEN boş kalırsa auth kapanır — sessiz ve
        tehlikeli varsayılan). Bu yüzden sözleşme zincirin tamamını arar:
        compose dosyayı servise geçiriyor mu, şablon belgeliyor mu, servis
        okuyor mu.
        """
        self.assertIn("hezarfen_rag.env", self.y)
        sablon = _oku(".env.example")
        kaynak = "\n".join(
            f.read_text(encoding="utf-8")
            for f in sorted(pathlib.Path(_KOK, "src").rglob("*.py"))
        )
        for k in ("RAG_SERVICE_TOKEN", "RAG_ALLOWED_HOSTS", "RAG_USER_DAILY_USD"):
            self.assertIn(k, sablon, f"{k} .env.example'da belgelenmemiş")
            self.assertIn(k, kaynak, f"{k} servis kaynağında okunmuyor")


class EntrypointTests(unittest.TestCase):
    def test_factory_exists_and_has_no_import_side_effect(self):
        """Modülü içe aktarmak ısıtma başlatmamalı."""
        import inspect
        from src.service import http_app
        self.assertTrue(callable(http_app.create_app_with_warmup))
        kaynak = inspect.getsource(http_app)
        self.assertNotIn("\napp = create_app", kaynak)


if __name__ == "__main__":
    unittest.main()
