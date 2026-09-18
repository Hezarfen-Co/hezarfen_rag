"""hab/2 QUIC taşıması — RAG servisi backend'in köprüsüne DIAL-OUT eder.

Şekil (`hezarfen_backend/src/ai/protocol.rs:3-7`): backend QUIC **sunucusudur**,
AI servisleri ona BAĞLANIR. Bu yüzden RAG hiçbir port açmaz: NAT ardında
yaşayabilir ve serbestçe yeniden başlayabilir.

Bu modülün TEK işi taşımadır: el sıkışma, kayıt, canlı tutma, gelen `Request`
çerçevesini `Dispatcher`a verme ve yeniden bağlanma. Çerçevenin ANLAMI
(yetenek yönlendirmesi, kiracılık, okul eko'su) `dispatch.py`de; tel biçimi
`contract.py`de. Üçü ayrı tutulur ki her biri diğerleri olmadan test edilebilsin
— bu deponun `bridge/` paketindeki ayrımın aynısı.

Desen, kanıtlanmış bir istemciden alındı: `hezarfen_zeka/service/src/bridge.py`
(aynı backend, aynı `hab/2`, üretimde kayıt oluyor). Dört yerde bilinçli olarak
ayrılır:

1. **İş yönü.** ZEKA `insight.*` YAZAR (backend'in açtığı akışlara cevap verir
   ve kendi okuma/yazma akışlarını açar). RAG `Request`leri CEVAPLAR ve
   `rag.index` için kendi İSTEMCİ akışlarını açar: her ek dosyanın baytları
   ayrı bir çift yönlü akışta `BlobRequest` → `BlobResponse` başlığı → tam
   `size` HAM bayt olarak okunur (`read_blob`; şekil `protocol.rs:25-31`).
   `rag.chat` hâlâ okul verisi istemez: kapsamı çerçeve taşır.
2. **Yetenekler.** İlan edilen küme `rag.chat` + `rag.index` + `rag.summarize` +
   `rag.questions`tur (`ADVERTISED_CAPABILITIES`). Dispatcher `chat.reply`ı da
   KARŞILAR (backend yollarsa cevaplanır) ama onu İLAN ETMEYİZ: o yetenek
   chatbot'undur ve ilan etmek sohbet trafiğini RAG'e yönlendirmeye davetiye
   olurdu.
3. **Redler tiplidir.** Kayıt reddi (`unauthorized`, `unsupported_protocol`)
   loglanır; süreç ÇIKMAZ.
4. **`rag.index` SUNULUR.** Gövdesi `bridge/dispatch.py` → `service/notes_index.py`;
   blob akışını bu modül açar (`_LoopBlobReader` ile executor thread'inden
   köprülenir) ve not indeksi süreç-içidir (`index/notes.py`).

BOOT POLİTİKASI (uygulanan; testle sabitlenen):
  * **Backend YOKKEN süreç DÜŞMEZ.** `run_forever` hiçbir hatada çıkmaz; üstel
    geri çekilmeyle (`AI_RECONNECT_SECS` .. `AI_RECONNECT_MAX_SECS`, jitter'li)
    yeniden dener ve backend geldiğinde KENDİLİĞİNDEN bağlanır.
  * **HTTP yüzeyi etkilenmez.** Köprü ayrı bir arka plan thread'inde koşar
    (`start_in_background`), yani uvicorn'un olay döngüsünü tutmaz ve bir
    taşıma hatası bir HTTP yanıtını geciktirmez.
  * **Token yoksa da denenir.** Uydurma bir varsayılan okul gibi varsayılan bir
    token da İCAT EDİLMEZ: backend `unauthorized` der, biz bekleyip yeniden
    deneriz (kalıcı rette bekleme tavana çekilir, denemek bırakılmaz).

GÜVENLİK NOTU (TLS): sertifika `GET /ai/certificate` ile DÜZ HTTP üzerinden
çekilir — kardeş servislerin hepsi bunu yapıyor ve bu bir TOFU (trust on first
use) tavizidir: yolda araya giren biri kendi sertifikasını pinletebilir.
`AI_TLS_FINGERPRINT` verilirse bu kapanır (PEM'den DER çıkarılır, SHA-256'sı
BURADA hesaplanır ve beklenenle karşılaştırılır); verilmezse davranış
değişmez, yalnız her açılışta `warn` loglanır ki operatör neyi açık bıraktığını
bilsin.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import inspect
import json
import os
import random
import ssl
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import partial

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ConnectionTerminated, QuicEvent, StreamDataReceived

from .contract import (AI_ALPN, AI_IDLE_TIMEOUT_SECS, AI_KEEPALIVE_SECS,
                       AI_MAX_CONCURRENT_PER_WORKER, AI_RAG_CHAT_CAPABILITY,
                       AI_RAG_INDEX_CAPABILITY, AI_RAG_QUESTIONS_CAPABILITY,
                       AI_RAG_SUMMARIZE_CAPABILITY, CERTIFICATE_PATH,
                       GREETING_TIMEOUT_SECS, BridgeFrameError, FrameStream,
                       HandshakeRejected, build_hello, encode_frame,
                       parse_greeting)
from .dispatch import Dispatcher

# --- günlük -----------------------------------------------------------------
# Backend'in kardeş servislerindeki desen: `logging` modülü YOK, `[önek]`
# damgalı `print(..., flush=True)`. Konteyner günlüğünde satır satır okunur.

_LOG_LEVELS = {"debug": 10, "info": 20, "warn": 30, "warning": 30, "error": 40}
DEFAULT_LOG_LEVEL = "info"

_active_level = _LOG_LEVELS[DEFAULT_LOG_LEVEL]


def set_log_level(name: str) -> None:
    global _active_level
    _active_level = _LOG_LEVELS.get(str(name).strip().lower(),
                                    _LOG_LEVELS[DEFAULT_LOG_LEVEL])


def log(level: str, message: str) -> None:
    if _LOG_LEVELS.get(level, _LOG_LEVELS[DEFAULT_LOG_LEVEL]) >= _active_level:
        print(f"[kopru] {message}", flush=True)


# --- yapılandırma -----------------------------------------------------------
# Filo ad sözleşmesi (2026-09-17): köprü anahtarları `AI_*`dır ve kardeş
# servislerle AYNIDIR. Yeni ad İCAT EDİLMEZ; kardeşlerle aynı anahtar aynı
# anlama gelir.

DEFAULT_BRIDGE_HOST = "hezarfen_backend"
DEFAULT_BRIDGE_PORT = 8090
DEFAULT_BACKEND_URL = "http://hezarfen_backend:7656"
CERT_FETCH_TIMEOUT_SECS = 10.0
"""`GET /ai/certificate` için HTTP zaman aşımı."""
BLOB_HEADER_TIMEOUT_SECS = 30.0
"""Bir blob akışının BAŞLIK çerçevesi için bekleme: backend reddi ya da `ok`."""
BLOB_BODY_TIMEOUT_SECS = 120.0
"""Gövde için bekleme. backend gövdeyi 64 KiB'lik parçalarla akıtır
(`server.rs::write_blob_body`) ve her yazıya kendi takılma sınırını koyar; bu
sınır bizim tarafımızda, not indekslemesinin son tarihinin (120 s) altında."""


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value is not None and value.strip() else default


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} tamsayı olmalı, alınan: {raw!r}") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} {minimum}..{maximum} arasında olmalı, alınan: {value}")
    return value


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} sayı olmalı, alınan: {raw!r}") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} {minimum}..{maximum} arasında olmalı, alınan: {value}")
    return value


@dataclass(frozen=True)
class Settings:
    """Köprünün ayarları — ortamdan bir kez okunur, sonra değişmez."""

    host: str = DEFAULT_BRIDGE_HOST
    port: int = DEFAULT_BRIDGE_PORT
    backend_url: str = DEFAULT_BACKEND_URL
    server_name: str = "localhost"
    service: str = "rag"
    token: str = ""
    tls_fingerprint: str = ""
    max_concurrent: int = 4
    reconnect_secs: float = 3.0
    reconnect_max_secs: float = 120.0

    @classmethod
    def from_env(cls) -> "Settings":
        log_level = _env_str("LOG_LEVEL", DEFAULT_LOG_LEVEL)
        set_log_level(log_level)
        return cls(
            host=_env_str("AI_BRIDGE_HOST", DEFAULT_BRIDGE_HOST),
            port=_env_int("AI_BRIDGE_PORT", DEFAULT_BRIDGE_PORT, 1, 65535),
            # Sertifikanın çekildiği HTTP adresi QUIC adresinden AYRIDIR.
            backend_url=_env_str("AI_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/"),
            server_name=_env_str("AI_TLS_SERVER_NAME", "localhost"),
            service=_env_str("AI_SERVICE_NAME", "rag"),
            token=_env_str("AI_SHARED_TOKEN", ""),
            tls_fingerprint=_env_str("AI_TLS_FINGERPRINT", "").strip().lower()
            .replace(":", ""),
            max_concurrent=_env_int("AI_MAX_CONCURRENT", 4, 1,
                                    AI_MAX_CONCURRENT_PER_WORKER),
            reconnect_secs=_env_float("AI_RECONNECT_SECS", 3.0, 0.05, 300.0),
            reconnect_max_secs=_env_float("AI_RECONNECT_MAX_SECS", 120.0, 0.1, 3600.0),
        )

    def summary(self) -> str:
        """Tek satırlık açılış özeti. SIR İÇERMEZ (`token` yalnız var/yok)."""
        return (f"servis='{self.service}' hedef={self.host}:{self.port} "
                f"backend={self.backend_url} tls_ad={self.server_name} "
                f"tls_parmak_izi={'PINLİ' if self.tls_fingerprint else 'TOFU(pinsiz)'} "
                f"token={'tanımlı' if self.token else 'TANIMSIZ'} "
                f"max_eşzamanlı={self.max_concurrent} "
                f"yeniden_bağlanma={self.reconnect_secs}s..{self.reconnect_max_secs}s")


# --- sertifika --------------------------------------------------------------


def _leaf_der_from_pem(pem: str) -> bytes:
    """PEM zincirinin İLK sertifikasını DER olarak çıkarır.

    Backend'in ilan ettiği parmak izi tam olarak bunun SHA-256'sıdır
    (`ai/tls.rs:150-153`: `hex::encode(Sha256::digest(leaf.as_ref()))` — küçük
    harf hex, iki nokta yok)."""
    begin, end = "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"
    start = pem.find(begin)
    stop = pem.find(end, start + 1)
    if start < 0 or stop < 0:
        raise RuntimeError("sertifika PEM gövdesi bulunamadı")
    body = pem[start + len(begin):stop]
    try:
        return base64.b64decode("".join(body.split()))
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(f"sertifika PEM gövdesi base64 değil: {exc}") from exc


def fetch_certificate(settings: Settings) -> str:
    """`GET /ai/certificate` ile köprü sertifikasını çek.

    HER YENİDEN BAĞLANMADA çağrılır, yalnız açılışta değil: `AI_TLS_CERT` ve
    `AI_TLS_KEY` boşsa backend her boot'ta sertifikasını YENİDEN üretir
    (`ai/tls.rs:37-46`), yani eski PEM'e güvenmek bağlantıyı kırar.

    Sunucunun bildirdiği `fingerprint_sha256` alanı DOĞRULAMA İÇİN KULLANILMAZ
    (sertifikayı uyduran taraf yanındaki parmak izini de uydurur); yalnız
    loglanır ve bizim hesabımızla çapraz denetlenir."""
    url = f"{settings.backend_url}{CERTIFICATE_PATH}"
    with urllib.request.urlopen(url, timeout=CERT_FETCH_TIMEOUT_SECS) as resp:
        govde = json.loads(resp.read())
    pem = govde.get("certificate_pem")
    if not pem:
        raise RuntimeError(f"{url} beklenen `certificate_pem` alanını döndürmedi")

    hesaplanan = hashlib.sha256(_leaf_der_from_pem(pem)).hexdigest()
    bildirilen = str(govde.get("fingerprint_sha256", "")).strip().lower().replace(":", "")
    if bildirilen and bildirilen != hesaplanan:
        raise RuntimeError("sertifika tutarsız: bildirilen parmak izi PEM'den "
                           f"hesaplananla uyuşmuyor ({bildirilen[:12]} ≠ "
                           f"{hesaplanan[:12]})")

    if settings.tls_fingerprint:
        if hesaplanan != settings.tls_fingerprint:
            raise RuntimeError("sertifika parmak izi PINLENEN değerle uyuşmuyor; "
                               f"bağlanılmıyor (beklenen "
                               f"{settings.tls_fingerprint[:12]}, gelen "
                               f"{hesaplanan[:12]})")
        log("info", f"sertifika alındı ve PINLENDİ (fingerprint {hesaplanan[:12]})")
    else:
        log("warn", f"sertifika alındı (fingerprint {hesaplanan[:12]}) — "
                    "AI_TLS_FINGERPRINT tanımsız, TOFU ile güveniliyor; üretimde "
                    "parmak izini pinleyin")
    return pem


def build_quic_configuration(settings: Settings, cert_pem: str) -> QuicConfiguration:
    """ALPN `hab/2`, sertifika doğrulaması AÇIK (self-signed'a PİNLENEREK)."""
    quic_config = QuicConfiguration(is_client=True, alpn_protocols=[AI_ALPN])
    quic_config.server_name = settings.server_name
    quic_config.verify_mode = ssl.CERT_REQUIRED
    # `cadata` BAYT olmalı: aioquic onu doğrudan `load_pem_x509_certificates`e
    # verir ve orada `bytes.split(b"-----BEGIN CERTIFICATE-----")` çağrılır.
    # Metin geçirmek HER bağlantıyı `TypeError` ile düşürür.
    quic_config.load_verify_locations(cadata=cert_pem.encode("ascii"))
    quic_config.idle_timeout = AI_IDLE_TIMEOUT_SECS
    return quic_config


# --- yetenek ilanı ----------------------------------------------------------

#: `Hello`da İLAN EDİLEN yetenekler. Dispatcher'ın karşıladığı kümenin ALT
#: KÜMESİDİR: `chat.reply`ı dispatcher karşılar ama ilan ETMEYİZ (o yetenek
#: chatbot'undur; ilan etmek backend'in sohbet trafiğini RAG'e yönlendirmesine
#: davetiye olurdu).
ADVERTISED_CAPABILITIES = (AI_RAG_CHAT_CAPABILITY, AI_RAG_INDEX_CAPABILITY,
                           AI_RAG_SUMMARIZE_CAPABILITY, AI_RAG_QUESTIONS_CAPABILITY)


def advertised(dispatcher: Dispatcher) -> tuple[str, ...]:
    """İlan edilecek yetenekler — dispatcher'ın desteklediklerinden SEÇİLİR.

    Böylece iki liste ayrışamaz: yetenek adı değişirse ya da dispatcher bir
    yeteneği bırakırsa bu bir `ValueError` olur (sessiz bir "ilan var, cevap
    yok" durumu değil)."""
    destek = set(dispatcher.capabilities)
    eksik = [c for c in ADVERTISED_CAPABILITIES if c not in destek]
    if eksik:
        raise ValueError("dispatcher şu yetenekleri karşılamıyor, ilan edilemez: "
                         f"{', '.join(eksik)}")
    return ADVERTISED_CAPABILITIES


# --- bağlantı ---------------------------------------------------------------


class BridgeTransport(QuicConnectionProtocol):
    """Tek bir QUIC bağlantısı: kontrol akışı + backend'in açtığı iş akışları."""

    def __init__(self, *args, settings: Settings, handler, capabilities,
                 dispatcher=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._settings = settings
        self._handler = handler
        self._capabilities = tuple(capabilities)
        self._dispatcher = dispatcher
        self._streams: dict[int, FrameStream] = {}
        self._control_sid: int | None = None
        self._ping_uid = 0
        self._tasks: set[asyncio.Future] = set()
        self.worker_id = ""

    # -- olay döngüsü --

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, StreamDataReceived):
            sid = event.stream_id
            stream = self._streams.get(sid)
            if stream is None:
                # QUIC akış kimliği: alt iki bit yönü ve tipi söyler.
                # 0 = istemci başlatımlı çift yönlü (bizim açtığımız),
                # 1 = SUNUCU başlatımlı çift yönlü (backend'in iş akışı).
                # Tek yönlü akışlar (2, 3) bu protokolde kullanılmaz.
                #
                # İstemci başlatımlı bir akışı yalnızca BİZ açarız ve okuyucusunu
                # açarken kaydederiz; bugün hiç açmıyoruz. Kaydı olmayan bir
                # akışa okuyucu kurmak, kimsenin okumayacağı bir tamponu
                # bağlantının ömrü boyunca tutmak olurdu. Düşer.
                if sid % 4 != 1:
                    return
                stream = FrameStream()
                self._streams[sid] = stream
                task = asyncio.ensure_future(self._serve_request(sid, stream))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            stream.feed(event.data, event.end_stream)
        elif isinstance(event, ConnectionTerminated):
            # Bekleyen her okuyucuya EOF ver; yoksa sonsuza kadar beklerler.
            for stream in self._streams.values():
                stream.feed(b"", end=True)

    def _send_frame(self, sid: int, obj, end: bool) -> None:
        self._quic.send_stream_data(sid, encode_frame(obj), end_stream=end)
        self.transmit()

    # -- kontrol akışı --

    async def register(self) -> str:
        """İlk istemci başlatımlı akışı aç, `Hello` yaz, `Greeting` oku.

        Akış KAPATILMAZ (`end=False`): ömür boyu açık kalır ve kapanması
        backend için kayıttan düşme sinyalidir (`ai/protocol.rs:11-14`)."""
        sid = self._quic.get_next_available_stream_id()
        self._control_sid = sid
        stream = FrameStream()
        self._streams[sid] = stream
        hello = build_hello(self._settings.service, self._capabilities,
                            self._settings.token, self._settings.max_concurrent)
        self._send_frame(sid, hello, end=False)
        greeting = await asyncio.wait_for(stream.read_frame(),
                                          timeout=GREETING_TIMEOUT_SECS)
        self.worker_id = parse_greeting(greeting)
        # Blob okuma yolu BURADA takılır: `rag.index` executor thread'inde koşar
        # (PING'ler durmasın) ve o thread'den QUIC akışı açmak bu köprüyü
        # (`run_coroutine_threadsafe`) gerektirir.
        if self._dispatcher is not None:
            self._dispatcher.blob_reader = _LoopBlobReader(self)
        log("info", f"kayıt başarılı: worker_id={self.worker_id} "
                    f"yetenekler={','.join(self._capabilities)}")
        return self.worker_id

    # -- istemci başlatımlı akışlar: blob okuma --
    async def read_blob(self, request: dict, *, max_bytes: int,
                        header_timeout: float = BLOB_HEADER_TIMEOUT_SECS,
                        body_timeout: float = BLOB_BODY_TIMEOUT_SECS):
        """Bir ekin baytlarını KENDİ istemci akışında oku.

        Şekil (`protocol.rs:25-31`): bir `BlobRequest` yaz, gönderme tarafını
        bitir, BİR `BlobResponse` başlık çerçevesi oku; `ok` ise tam `size`
        HAM bayt gelir (çerçeve DEĞİL — `AI_MAX_FRAME_BYTES` onları sınırlamaz),
        sonra akış biter. Dönüş: `(header, bytes)`; red `BlobReadRefused`.
        """
        from .contract import BlobReadRefused
        sid = self._quic.get_next_available_stream_id()
        stream = FrameStream()
        self._streams[sid] = stream
        try:
            self._send_frame(sid, request, end=True)
            header = await asyncio.wait_for(stream.read_frame(), timeout=header_timeout)
            if not isinstance(header, dict):
                raise BlobReadRefused("bad_header", "blob başlığı nesne değil")
            if header.get("status") != "ok":
                raise BlobReadRefused(str(header.get("code") or "unknown"),
                                      str(header.get("message") or ""))
            size = int(header.get("size") or 0)
            if size < 0 or size > max_bytes:
                raise BlobReadRefused(
                    "too_large", f"blob {size} bayt: sınır {max_bytes}")
            body = await asyncio.wait_for(stream.read_exact(size),
                                          timeout=body_timeout)
            return header, body
        except BlobReadRefused:
            raise
        except asyncio.TimeoutError as exc:
            raise BlobReadRefused("timeout", "blob akışı zaman aşımına uğradı") from exc
        except (BridgeFrameError, EOFError, ValueError) as exc:
            raise BlobReadRefused("bad_header", str(exc)) from exc
        finally:
            self._streams.pop(sid, None)

    async def keepalive(self) -> None:
        """QUIC PING. Uygulama düzeyinde heartbeat ÇERÇEVESİ yoktur
        (`ai/protocol.rs:13-14`); boşta kalma zaman aşımını bu önler."""
        while True:
            await asyncio.sleep(AI_KEEPALIVE_SECS)
            self._ping_uid += 1
            try:
                self._quic.send_ping(self._ping_uid)
                self.transmit()
            except Exception:
                return

    # -- iş yönü: backend'in açtığı akışlar --

    async def _serve_request(self, sid: int, stream: FrameStream) -> None:
        """Backend'in açtığı bir akışta gelen TEK `Request`i karşıla.

        Çerçevenin ANLAMI burada yorumlanmaz: sözlük `Dispatcher.handle`e
        gider, dönen sözlük (ya da `None`) teline yazılır. `None` "cevap YAZMA"
        demektir — okulsuz/bozuk bir çerçevede uydurulacak bir okul yoktur ve
        backend'in kendi kuralı da *"there is no default and no fallback"*
        der; **akış düşer, BAĞLANTI düşmez** (`dispatch.py` başlığı)."""
        try:
            frame = await stream.read_frame()
        except (BridgeFrameError, EOFError, ValueError) as exc:
            log("warn", f"istek akışı okunamadı (sid={sid}): {exc}")
            self._streams.pop(sid, None)
            return

        try:
            cevap = await self._handle(frame)
        except Exception as exc:                       # noqa: BLE001
            # Dispatcher kendi redlerini TİPLİ cevaplara çevirir; buraya düşen
            # şey beklenmeyen bir çalışma hatasıdır. Akışı sessizce düşürmek
            # backend'i zaman aşımına uğratırdı: küçük bir `internal` yazılır ve
            # BAĞLANTI ayakta kalır.
            log("error", f"istek işlenemedi (sid={sid}): {exc}")
            cevap = _err_frame(frame, "internal", "beklenmeyen hata")
        if cevap is None:
            self._streams.pop(sid, None)
            return
        self._finish(sid, cevap)

    async def _handle(self, frame):
        """Kancayı çağır. Eşzamanlı kanca varsayılan executor'a ATILIR.

        Boru hattı (retrieval + LLM) işlemci/GPU yoğundur; olay döngüsünde
        koşarsa `keepalive()` PING'lerini de durdurur ve backend boşta kalma
        penceresini (30 s) aşan tek bir istek, cevabını yazamadan bağlantının
        düşürülmesine yol açardı."""
        if inspect.iscoroutinefunction(self._handler):
            return await self._handler(frame)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._handler, frame)

    def _finish(self, sid: int, response: dict) -> None:
        try:
            self._send_frame(sid, response, end=True)
        except BridgeFrameError as exc:
            # Cevap çerçeve tavanını aştı: sessizce düşürmek yerine KÜÇÜK bir
            # hata yaz, yoksa backend akışı bekleyip zaman aşımına uğrar.
            log("warn", f"cevap çerçeve sınırını aştı (sid={sid}): {exc}")
            try:
                self._send_frame(sid, _err_frame(response, exc.code, exc.message),
                                 end=True)
            except Exception as inner:                 # noqa: BLE001
                log("error", f"hata çerçevesi de yazılamadı: {inner}")
        except Exception as exc:                       # noqa: BLE001
            log("error", f"cevap yazılamadı (sid={sid}): {exc}")
        finally:
            self._streams.pop(sid, None)


class _LoopBlobReader:
    """`rag.index`'in blob okuması için thread ↔ olay döngüsü köprüsü.

    Boru hattı (chunk + gömme) executor thread'inde koşar; QUIC akışı ise olay
    döngüsünde açılır. Executor thread'inden `run_coroutine_threadsafe` ile
    geçilir ve SENKRON beklenir — `rag.index` zaten arka planda, kimse
    bekleyemez.
    """

    def __init__(self, protocol) -> None:
        self._protocol = protocol

    def read(self, request: dict, *, max_bytes: int):
        from concurrent.futures import TimeoutError as FutureTimeout
        from .contract import BlobReadRefused
        loop = getattr(self._protocol, "_loop", None)
        if loop is None or loop.is_closed():
            raise BlobReadRefused("unavailable", "köprü olay döngüsü yok/ kapalı")
        future = asyncio.run_coroutine_threadsafe(
            self._protocol.read_blob(request, max_bytes=max_bytes), loop)
        try:
            return future.result(
                timeout=BLOB_HEADER_TIMEOUT_SECS + BLOB_BODY_TIMEOUT_SECS)
        except FutureTimeout as exc:
            raise BlobReadRefused("timeout", "blob okuması zaman aşımına uğradı") from exc


def _err_frame(kaynak, code: str, message: str) -> dict:
    """Türsüz bir hata için küçük bir `Response{status:"err"}` çerçevesi.

    `id`/`school` elden geldiğince AYNEN yankılanır (backend kuralı); elde
    yoksa boş kalır — uydurulmaz."""
    kaynak = kaynak if isinstance(kaynak, dict) else {}
    return {"status": "err", "id": str(kaynak.get("id") or ""),
            "school": str(kaynak.get("school") or ""),
            "code": code, "message": message}


# --- yaşam döngüsü ----------------------------------------------------------


async def run_once(settings: Settings, dispatcher: Dispatcher,
                   capabilities: tuple[str, ...]) -> None:
    """Sertifikayı çek, bağlan, kaydol, bağlantı kapanana kadar bekle."""
    cert_pem = fetch_certificate(settings)
    quic_config = build_quic_configuration(settings, cert_pem)
    log("info", f"{settings.host}:{settings.port} adresine bağlanılıyor "
                f"(ALPN {AI_ALPN})")
    create = partial(BridgeTransport, settings=settings,
                     handler=dispatcher.handle, dispatcher=dispatcher,
                     capabilities=capabilities)
    async with connect(settings.host, settings.port, configuration=quic_config,
                       create_protocol=create) as connection:
        await connection.wait_connected()
        await connection.register()
        keepalive_task = asyncio.ensure_future(connection.keepalive())
        try:
            await connection.wait_closed()
        finally:
            keepalive_task.cancel()
    log("info", "bağlantı kapandı")


def next_backoff(current: float, settings: Settings) -> float:
    """Üstel geri çekilme: ikiye katla ve tavanda dur.

    JITTER BURADA EKLENMEZ — uyumadan hemen önce eklenir: rastgelelik bir
    sonraki beklemenin TABANINI kaydırmamalı, yoksa birikerek gerçek tavanı
    aşar. Bu fonksiyon deterministik kalır."""
    return min(current * 2.0, settings.reconnect_max_secs)


async def run_forever(settings: Settings, dispatcher: Dispatcher) -> int:
    """Bağlantıyı sürekli ayakta tutar. **HİÇBİR HATADA ÇIKMAZ.**

    Kardeş servislerden farkı: podcast `unsupported_protocol`/`unauthorized`
    alınca `exit 2` yapar; `restart: unless-stopped` ile bu sonsuz bir
    crash-loop üretir ve backend düzeltildiğinde servis KENDİLİĞİNDEN
    toparlanmaz — operatörün elle müdahalesi gerekir. Biz kodu loglayıp
    beklemeyi tavana çekeriz: kalıcı bir redde gürültü yapmadan bekleriz."""
    capabilities = advertised(dispatcher)
    log("info", f"RAG köprüsü başlıyor: {settings.summary()}")
    if not settings.token:
        log("warn", "AI_SHARED_TOKEN tanımsız — kayıt `unauthorized` ile "
                    "reddedilecek; yine de deneniyor (çıkmıyoruz)")
    backoff = settings.reconnect_secs
    while True:
        try:
            await run_once(settings, dispatcher, capabilities)
            backoff = settings.reconnect_secs     # sağlıklı oturum: sayacı sıfırla
        # SIRA ÖNEMLİ: Python 3.11'den beri `asyncio.TimeoutError` yerleşik
        # `TimeoutError`dir ve o da `OSError`in alt sınıfıdır. Zaman aşımı
        # yakalayıcısı OSError'DAN ÖNCE gelmek zorunda; altına konursa
        # ERİŞİLEMEZ olur ve el sıkışma zaman aşımı "backend'e ulaşılamadı"
        # diye loglanır.
        except asyncio.TimeoutError:
            log("warn", "el sıkışma zaman aşımına uğradı")
            backoff = next_backoff(backoff, settings)
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            log("warn", f"backend'e ulaşılamadı: {exc}")
            backoff = next_backoff(backoff, settings)
        except HandshakeRejected as exc:
            if exc.permanent:
                log("error", f"{exc} — yapılandırma değişmeden düzelmez; "
                             "yine de çıkmıyoruz, geri çekilerek yeniden denenecek")
                backoff = settings.reconnect_max_secs
            else:
                log("error", str(exc))
                backoff = next_backoff(backoff, settings)
        except Exception as exc:                       # noqa: BLE001
            log("error", f"bağlantı hatası: {exc}")
            backoff = next_backoff(backoff, settings)
        delay = backoff + random.uniform(0.0, min(backoff, 5.0))
        log("info", f"{delay:.1f}s sonra yeniden denenecek")
        await asyncio.sleep(delay)


def start_in_background(service, *, settings: Settings | None = None,
                        name: str = "kopru") -> threading.Thread:
    """Köprüyü arka plan thread'inde başlat (uvicorn süreci için).

    NEDEN THREAD, NEDEN GÖREV DEĞİL: HTTP yüzeyi (uvicorn) kendi olay
    döngüsünde koşar ve köprü ondan BAĞIMSIZ olmalıdır — bir taşıma hatası bir
    HTTP yanıtını geciktirmemeli, HTTP'nin yeniden başlaması köprüyü kesmemeli.
    Deponun kendi deseni budur (ısıtma thread'i, `http_app._isit`).

    `run_forever` hiçbir taşıma hatasında çıkmaz; thread yine de beklenmedik bir
    hatayla ölürse (örneğin `advertised()` uyumsuzluğu) bu YUTULMAZ: loglanır ve
    HTTP yüzeyi etkilenmeden çalışmaya devam eder."""
    ayarlar = settings or Settings.from_env()

    def _kos() -> None:
        try:
            asyncio.run(run_forever(ayarlar, Dispatcher(service)))
        except Exception as exc:                       # noqa: BLE001
            log("error", f"köprü thread'i durdu: {exc}")

    thread = threading.Thread(target=_kos, name=name, daemon=True)
    thread.start()
    return thread
