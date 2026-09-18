"""hab/2 QUIC taşıması — kayıt, dağıtım, redler ve yeniden bağlanma.

Testler GERÇEK bir QUIC el sıkışması koşar: sahte sunucu (`_fake_bridge.py`)
aioquic ile 127.0.0.1'de ayağa kalkar, istemci ona dial-out eder. Ağ yoktur
(dışarıya hiçbir bağlantı kurulmaz), veritabanı yoktur, model yoktur: servis
çifti yalnız `chat(req)` metodu olan bir sahte.

Her testin ölçtüğü iddia başlıkta yazar; hangi davranış gerilerse test kırılır
(örneğin `chat.reply` de ilan edilirse kayıt testi, yeniden bağlanma kaldırılırsa
kopma testi düşer)."""
from __future__ import annotations

import asyncio
import contextlib
import os
import unittest
import unittest.mock

from src.bridge.dispatch import Dispatcher
from src.bridge.transport import Settings, run_forever, set_log_level
from tests.unit._fake_bridge import FakeBridge

#: Sahte servisin döndürdüğü kanonik cevap (boru hattı çalıştırılmaz).
CEVAP = {"text": "Hücre, canlıların temel yapı birimidir.",
         "abstained": False, "reason": "",
         "citations": [{"n": 1, "doc_id": "DOC-1", "pages": [12],
                        "span_ids": ["s1"], "ders": "biyoloji"}]}


class _SahteServis:
    """`Dispatcher`ın beklediği tek şey: `chat(req)`. Çağrıları kaydeder."""

    def __init__(self) -> None:
        self.cagrilar: list[dict] = []

    def chat(self, req: dict) -> dict:
        self.cagrilar.append(req)
        return dict(CEVAP)


def _olu_port() -> int:
    """Kimsenin dinlemediği bir TCP portu: bağlan ve bırak (anında red)."""
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _ayarlar(bridge: FakeBridge, *, port: int | None = None, **ustune) -> Settings:
    """Sahte sunucuya bakan ayarlar; geri çekilme testler için kısaltılır.

    `port` AÇIKÇA verilebilir: sunucunun QUIC'i kapalıyken (`close_quic()`)
    port özelliği okunamaz — "backend yok" senaryosu tam da o durumdur."""
    deger = dict(host="127.0.0.1", port=bridge.quic_port if port is None else port,
                 backend_url=bridge.backend_url, server_name="localhost",
                 service="rag", token=bridge.token, tls_fingerprint="",
                 reconnect_secs=0.05, reconnect_max_secs=0.2)
    deger.update(ustune)
    return Settings(**deger)


@contextlib.asynccontextmanager
async def _calisan_kopru(bridge: FakeBridge, servis: _SahteServis, *,
                         indexer=None, **ustune):
    """Köprüyü arka planda koştur, çıkışta temizle."""
    gorev = asyncio.ensure_future(
        run_forever(_ayarlar(bridge, **ustune), Dispatcher(servis, indexer=indexer)))
    try:
        yield gorev
    finally:
        gorev.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await gorev
        assert gorev.done()


class KopruTasimaTestleri(unittest.TestCase):
    def setUp(self) -> None:
        # Test çıktısı temiz kalsın: köprü normalde bilgi düzeyinde loglar.
        set_log_level("error")
        self.addCleanup(set_log_level, "info")

    # -- 1. kayıt ----------------------------------------------------------

    def test_kayit_hello_ile_yalniz_rag_yeteneklerini_ilan_eder(self):
        """`Hello`: protokol hab/2, servis adı, token ve İKİ yetenek.

        `chat.reply` de ilan edilirse bu test düşer: o yetenek chatbot'undur,
        ilan etmek backend'in sohbet trafiğini RAG'e yönlendirmesine davetiye
        olurdu (bkz. transport.ADVERTISED_CAPABILITIES)."""

        async def senaryo() -> None:
            bridge = FakeBridge()
            await bridge.start()
            try:
                async with _calisan_kopru(bridge, _SahteServis()) as gorev:
                    worker = await bridge.wait_for_worker(timeout=10)
                    hello = bridge.hellos[-1]
                    self.assertEqual(hello["protocol"], "hab/2")
                    self.assertEqual(hello["service"], "rag")
                    self.assertEqual(hello["token"], bridge.token)
                    self.assertEqual(hello["capabilities"],
                                     ["rag.chat", "rag.index"])
                    # Backend 1..=64 arasına kırpar; ilan edilen değer bu
                    # aralıkta olmalı, yoksa sessizce kırpılırdı.
                    self.assertTrue(1 <= hello["max_concurrent"] <= 64)
                    # ALPN kapısı: sunucu YALNIZ `hab/2` kabul ediyor ve kayıt
                    # gerçekten oluştu (ALPN uyuşmasa bağlantı hiç kurulmazdı).
                    self.assertEqual([w.worker_id for w in bridge.workers],
                                     [worker.worker_id])
                    self.assertFalse(gorev.done())
            finally:
                await bridge.stop()

        asyncio.run(senaryo())

    # -- 2. istek -> dağıtım -> cevap (okul eko'su) ------------------------

    def test_istek_dagiticiya_ulasir_ve_okulu_aynen_yankilar(self):
        """Cevap gerçekten boru hattından üretilir ve `school` AYNEN döner.

        Eko düşerse (`school` boş/başka bir değer) test kırılır; istek servise
        uğramazsa `servis.cagrilar` boş kalır."""

        async def senaryo() -> None:
            bridge = FakeBridge()
            await bridge.start()
            servis = _SahteServis()
            try:
                async with _calisan_kopru(bridge, servis):
                    await bridge.wait_for_worker(timeout=10)
                    cevap = await bridge.call(
                        "rag.chat", "okul-a",
                        {"message": "Hücre nedir?", "asker_role": "student",
                         "scope": [{"sinif": "10", "ders": "biyoloji"}]})
                    self.assertEqual(cevap["status"], "ok")
                    self.assertEqual(cevap["school"], "okul-a")
                    # Kimlik YANKILANIR: cevap gerçekten BU isteğe ait.
                    self.assertTrue(cevap["id"].startswith("FAKEREQ"))
                    self.assertEqual(cevap["payload"]["text"], CEVAP["text"])
                    self.assertEqual(cevap["payload"]["citations"][0]["doc_id"],
                                     "DOC-1")
                    # İstek SERVİSE ulaştı; okul/rol eşlemesi dağıtıcıda yapıldı.
                    gelen = servis.cagrilar[-1]
                    self.assertEqual(gelen["query"], "Hücre nedir?")
                    self.assertEqual(gelen["school"], "okul-a")
                    self.assertEqual(gelen["role"], {"role": "student"})
                    self.assertEqual(gelen["scope"],
                                     [{"sinif": "10", "ders": "biyoloji"}])
            finally:
                await bridge.stop()

        asyncio.run(senaryo())

    # -- 3. redler tipli, bağlantı ayakta ----------------------------------

    def test_gecersiz_okul_ve_bozuk_cerceve_tipli_reddedilir_baglanti_duser_degil(self):
        """Üç iddia: (a) geçersiz okul TİPLİ red + aynen eko, (b) okulsuz
        çerçevede cevap YAZILMAZ (akış düşer) ve süreç ÇÖKMEZ, (c) `rag.index`
        henüz sunulmadığını SÖYLER (sessiz "tamam" yok), (d) bağlantı ayakta."""

        async def senaryo() -> None:
            bridge = FakeBridge()
            await bridge.start()
            try:
                async with _calisan_kopru(bridge, _SahteServis()) as gorev:
                    await bridge.wait_for_worker(timeout=10)

                    # (a) Geçersiz okul kimliği: tipli red, okul AYNEN yankılanır.
                    akis = bridge.workers[-1].open_stream()
                    await akis.send({"id": "R-GECERSIZ", "school": "Okul A",
                                     "capability": "rag.chat",
                                     "payload": {"message": "x"}})
                    red = await akis.read()
                    akis.close()
                    self.assertEqual(red["status"], "err")
                    self.assertEqual(red["code"], "invalid_school")
                    self.assertEqual(red["school"], "Okul A")
                    self.assertEqual(red["id"], "R-GECERSIZ")

                    # (b) Okulsuz çerçeve: yankılanacak okul YOK → cevap yazılmaz,
                    # akış düşer, BAĞLANTI düşmez.
                    akis2 = bridge.workers[-1].open_stream()
                    await akis2.send({"id": "R-OKULSUZ", "capability": "rag.chat",
                                      "payload": {"message": "x"}})
                    with self.assertRaises(TimeoutError):
                        await akis2.read(timeout=0.5)
                    akis2.close()

                    # (c) `rag.index` SUNULUR: gövdesi eksikse TİPLİ reddedilir
                    # (uydurma "tamam" yok; gövde tam olduğunda yol aşağıdaki
                    # testte blob akışıyla uçtan uca koşar).
                    indeks = await bridge.call("rag.index", "okul-a",
                                               {"course_note": "N1"})
                    self.assertEqual(indeks["status"], "err")
                    self.assertEqual(indeks["code"], "malformed")
                    self.assertEqual(indeks["school"], "okul-a")

                    # (d) Hepsinin ardından normal istek cevaplanıyor.
                    sag = await bridge.call("rag.chat", "okul-a",
                                            {"message": "y",
                                             "asker_role": "teacher"})
                    self.assertEqual(sag["status"], "ok")
                    self.assertFalse(gorev.done())
            finally:
                await bridge.stop()

        asyncio.run(senaryo())

    # -- 4. kopma -> yeniden bağlanma --------------------------------------

    def test_kopmadan_sonra_yeniden_kaydolur_ve_istek_servis_etmeye_devam_eder(self):
        """Backend bağlantıyı düşürünce istemci YENİ bir worker olarak döner.

        Yeniden bağlanma kaldırılırsa `wait_for_worker` zaman aşımına uğrar ve
        test kırılır; geri gelmezse ikinci `call` da cevapsız kalır."""

        async def senaryo() -> None:
            bridge = FakeBridge()
            await bridge.start()
            try:
                async with _calisan_kopru(bridge, _SahteServis()):
                    birinci = await bridge.wait_for_worker(timeout=10)
                    bridge.drop_connections()
                    ikinci = await bridge.wait_for_worker(timeout=15)
                    self.assertNotEqual(birinci.worker_id, ikinci.worker_id)
                    self.assertGreaterEqual(len(bridge.registrations), 2)
                    cevap = await bridge.call("rag.chat", "okul-b",
                                              {"message": "x",
                                               "asker_role": "student"})
                    self.assertEqual(cevap["status"], "ok")
                    self.assertEqual(cevap["school"], "okul-b")
            finally:
                await bridge.stop()

        asyncio.run(senaryo())

    # -- 5. boot politikası: backend yokken ---------------------------------

    def test_backend_yokken_surec_cikmaz_ve_backend_gelince_kendiliginden_katilir(self):
        """BOOT POLİTİKASI: backend yokken süreç ayakta kalır, loglar ve
        yeniden dener; backend geldiğinde AYNI süreç kaydolur.

        İki ayrı erişilemezlik hâli ölçülür, çünkü ikisi farklı kod yollarıdır:
          (a) sertifika ucu da kapalı → her deneme ANINDA `URLError` (`OSError`)
              olur; `run_forever` bunu yakalamazsa/yutar ve ÇIKARSA test düşer.
          (b) QUIC kapalı, sertifika ucu ayakta → el sıkışma düşer; süreç
              beklemeye devam eder ve backend QUIC'i geri gelince kendiliğinden
              kaydolur (yeniden denemeyi bırakırsa `wait_for_worker` zaman
              aşımına uğrar)."""

        async def senaryo() -> None:
            bridge = FakeBridge()
            await bridge.start()
            port = bridge.quic_port
            olu_http = _olu_port()

            # (a) Tamamen erişilemez backend: her deneme anında düşer.
            ilk = asyncio.ensure_future(run_forever(
                Settings(host="127.0.0.1", port=port,
                         backend_url=f"http://127.0.0.1:{olu_http}",
                         server_name="localhost", service="rag",
                         token=bridge.token, reconnect_secs=0.05,
                         reconnect_max_secs=0.1),
                Dispatcher(_SahteServis())))
            try:
                await asyncio.sleep(0.3)
                self.assertFalse(ilk.done(), "erişilemeyen backend'de süreç ÇIKTI")
            finally:
                ilk.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ilk

            # (b) Sertifika çekilebiliyor, QUIC YOK (gerçek bir yeniden
            # başlatmanın ilk anı) → bekle, backend gelince katıl.
            bridge.close_quic()
            ayarlar = _ayarlar(bridge, port=port)
            gorev = asyncio.ensure_future(run_forever(ayarlar, Dispatcher(_SahteServis())))
            try:
                await asyncio.sleep(0.4)
                self.assertFalse(gorev.done(), "QUIC yokken süreç ÇIKTI")
                self.assertEqual(bridge.registrations, [])
                await asyncio.sleep(0.2)
                self.assertFalse(gorev.done(), "yeniden denemeyi bıraktı")
                await bridge.reopen_quic()
                worker = await bridge.wait_for_worker(timeout=15)
                self.assertEqual(worker.hello["service"], "rag")
                cevap = await bridge.call("rag.chat", "okul-a",
                                          {"message": "x", "asker_role": "student"})
                self.assertEqual(cevap["status"], "ok")
            finally:
                gorev.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await gorev
                await bridge.stop()

        asyncio.run(senaryo())


    # -- 6. TLS pinleme -----------------------------------------------------

    def test_yanlis_parmak_izi_baglanmaz_dogrusu_baglanir(self):
        """`AI_TLS_FINGERPRINT` doluysa sertifika PEM'den BURADA hesaplanan
        SHA-256 ile karşılaştırılır; uyuşmazsa BAĞLANILMAZ.

        Yalnız "pinlendi" demek yetmez: yanlış pinle yine de kaydolursa bu
        test düşer (o zaman pinleme bir süs olurdu)."""

        async def senaryo() -> None:
            bridge = FakeBridge()
            await bridge.start()
            try:
                yanlis = _ayarlar(bridge, tls_fingerprint="0" * 64)
                gorev = asyncio.ensure_future(
                    run_forever(yanlis, Dispatcher(_SahteServis())))
                try:
                    await asyncio.sleep(0.5)
                    self.assertEqual(bridge.registrations, [],
                                     "yanlış parmak iziyle BAĞLANDI")
                    self.assertFalse(gorev.done(), "pin uyuşmazlığında süreç ÇIKTI")
                finally:
                    gorev.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await gorev
                async with _calisan_kopru(
                        bridge, _SahteServis(),
                        tls_fingerprint=bridge.certificate.fingerprint):
                    await bridge.wait_for_worker(timeout=10)
            finally:
                await bridge.stop()

        asyncio.run(senaryo())


class OrtamAdlariTestleri(unittest.TestCase):
    def test_ayarlar_yalniz_filo_ai_adlarini_okur(self):
        """Köprü anahtarları `AI_*`dır ve kardeş servislerle AYNIDIR.

        Yeni bir ad icat edilirse (örneğin `RAG_BRIDGE_HOST`) bu test düşer:
        aşağıdaki aldatıcı adlar YOK SAYILIR, `AI_*` değerleri okunur."""
        ortam = {
            "AI_BRIDGE_HOST": "hezarfen_backend",
            "AI_BRIDGE_PORT": "8090",
            "AI_BACKEND_URL": "http://hezarfen_backend:7656/",
            "AI_TLS_SERVER_NAME": "localhost",
            "AI_SERVICE_NAME": "rag",
            "AI_SHARED_TOKEN": "test-token",
            "AI_TLS_FINGERPRINT": ":".join(["AB"] * 32),
            "AI_MAX_CONCURRENT": "6",
            "AI_RECONNECT_SECS": "1.5",
            "AI_RECONNECT_MAX_SECS": "60",
            # Aldatıcı adlar: okunmamalı.
            "RAG_BRIDGE_HOST": "yanlis",
            "BRIDGE_PORT": "1",
            "AI_BRIDGE_HOSTNAME": "yanlis",
        }
        with unittest.mock.patch.dict(os.environ, ortam, clear=True):
            ayar = Settings.from_env()
        self.assertEqual(ayar.host, "hezarfen_backend")
        self.assertEqual(ayar.port, 8090)
        self.assertEqual(ayar.backend_url, "http://hezarfen_backend:7656")
        self.assertEqual(ayar.service, "rag")
        self.assertEqual(ayar.token, "test-token")
        self.assertEqual(ayar.tls_fingerprint, "ab" * 32)
        self.assertEqual(ayar.max_concurrent, 6)
        self.assertEqual(ayar.reconnect_secs, 1.5)
        self.assertEqual(ayar.reconnect_max_secs, 60.0)
        # Özet SIR vermez: anahtarın kendisi değil, var/yok bilgisi yazılır.
        self.assertNotIn("test-token", ayar.summary())


class RagIndexBlobAkisiTestleri(unittest.TestCase):
    """`rag.index` uçtan uca: çerçeve → (sahte) dizinleyici → BLOB AKIŞI → cevap.

    Ölçülen iddia: ekin baytları kendi istemci akışında, ham olarak (çerçeve
    DEĞİL) gelir; cevap `files[].id`yi isteğin verdiği id ile AYNEN yankılar
    (backend `course_note_file.rag_doc_id`yi yalnız bu eşleşmeden doldurur).
    """

    BAYT = (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
            b"%%EOF\n" * 20)

    def test_ek_baytlari_blob_akisindan_okunur_ve_id_yankilanir(self):
        okumalar: list = []

        def sahte_indeksleyici(payload, *, school, blob_reader):
            meta = payload.files[0]
            header, data = blob_reader.read(
                {"id": f"ULID-{meta.id}", "school": school, "file": meta.id,
                 "on_behalf_of": payload.author},
                max_bytes=8 * 1024 * 1024)
            okumalar.append((header, data))
            return {"course_note": payload.course_note,
                    "chunks": 1,
                    "files": [{"id": meta.id, "doc_id": "5eda1f0a9c32"}],
                    "summary": f"'{payload.title}' notu indekslendi."}

        async def senaryo() -> None:
            bridge = FakeBridge()
            bridge.add_blob("01FILE", self.BAYT, name="kaynak.pdf",
                            content_type="application/pdf")
            await bridge.start()
            try:
                async with _calisan_kopru(bridge, _SahteServis(),
                                          indexer=sahte_indeksleyici):
                    await bridge.wait_for_worker(timeout=10)
                    cevap = await bridge.call("rag.index", "okul-a", {
                        "course_note": "01NOTE", "course": "01COURSE",
                        "author": "01AUTHOR", "title": "Hücre ve Canlılar",
                        "content": "Hücre, canlıların en küçük yapı birimidir.",
                        "files": [{"id": "01FILE", "name": "kaynak.pdf",
                                   "content_type": "application/pdf",
                                   "size": len(self.BAYT)}]})

                    self.assertEqual(cevap["status"], "ok")
                    self.assertEqual(cevap["school"], "okul-a")
                    govde = cevap["payload"]
                    self.assertEqual(govde["course_note"], "01NOTE")
                    # id AYNEN yankılanır → backend ekin satırını damgalar.
                    self.assertEqual(govde["files"][0]["id"], "01FILE")
                    self.assertEqual(govde["files"][0]["doc_id"], "5eda1f0a9c32")

                    # Baytlar ham aktı: çerçeve çözülmedi, tam boyutta geldi.
                    self.assertEqual(len(okumalar), 1)
                    header, data = okumalar[0]
                    self.assertEqual(header["status"], "ok")
                    self.assertEqual(header["size"], len(self.BAYT))
                    self.assertEqual(header["name"], "kaynak.pdf")
                    self.assertEqual(data, self.BAYT)

                    # İstek backend'e okul + ADINA OKUMA ile gitti.
                    istek = bridge.blob_requests[0]
                    self.assertEqual(istek["school"], "okul-a")
                    self.assertEqual(istek["file"], "01FILE")
                    self.assertEqual(istek["on_behalf_of"], "01AUTHOR")
            finally:
                await bridge.stop()

        asyncio.run(senaryo())

    def test_okunamayan_ek_indekslemeyi_durdurmaz(self):
        """Blob `not_found` derse dizinleme REDDEDİLMEZ: notun kendi metni
        indekslenir ve cevap hangi ekin okunamadığını söyler (backend eski
        satırı koruyacağı için "sessiz tamam" en kötü sonuçtur)."""
        cevaplar: list = []

        def sahte_indeksleyici(payload, *, school, blob_reader):
            from src.bridge.contract import BlobReadRefused
            hata = None
            try:
                blob_reader.read({"id": "ULID", "school": school,
                                  "file": payload.files[0].id,
                                  "on_behalf_of": payload.author},
                                 max_bytes=1 << 20)
            except BlobReadRefused as exc:
                hata = exc
            cevaplar.append(hata)
            return {"course_note": payload.course_note, "chunks": 2, "files": [],
                    "failed": [{"id": payload.files[0].id, "code": hata.code,
                                "message": hata.message}],
                    "summary": f"'{payload.title}' notu indekslendi."}

        async def senaryo() -> None:
            bridge = FakeBridge()          # blobs BOŞ: dosya yok
            await bridge.start()
            try:
                async with _calisan_kopru(bridge, _SahteServis(),
                                          indexer=sahte_indeksleyici):
                    await bridge.wait_for_worker(timeout=10)
                    cevap = await bridge.call("rag.index", "okul-a", {
                        "course_note": "01NOTE", "course": "01COURSE",
                        "author": "01AUTHOR", "title": "Hücre",
                        "content": "Hücre...",
                        "files": [{"id": "01YOK", "name": "yok.pdf",
                                   "content_type": "application/pdf",
                                   "size": 10}]})
                    self.assertEqual(cevap["status"], "ok")
                    self.assertEqual(cevap["payload"]["failed"][0]["code"],
                                     "not_found")
                    self.assertIsNotNone(cevaplar[0])
                    self.assertEqual(cevaplar[0].code, "not_found")
            finally:
                await bridge.stop()

        asyncio.run(senaryo())
