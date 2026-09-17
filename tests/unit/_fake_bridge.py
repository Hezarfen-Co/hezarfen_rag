"""Sahte backend köprüsü — TEST ALTYAPISI, üretim kodu DEĞİL.

Kardeş servisin kanıtlanmış deseni (`hezarfen_zeka/service/tests/fake_bridge/`):
aioquic ile gerçek bir QUIC sunucusu + sertifika için düz HTTP ucu, ikisi de
127.0.0.1'de ve işletim sisteminin verdiği boş portta — dışarıya HİÇBİR bağlantı
kurulmaz.

KASITLI OLARAK BAĞIMSIZ: bu dosya `src.bridge`ten hiçbir şey içe AKTARMAZ.
Çerçeveleme, el sıkışma ve ret kodları backend'in kendi kaynaklarından
(`ai/protocol.rs`, `ai/server.rs`) BAĞIMSIZ olarak burada yeniden yazılmıştır —
istemciyle aynı kodu paylaşan bir sahte sunucu, istemcinin hatasını da paylaşır
ve test hiçbir şey kanıtlamaz.
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import ipaddress
import json
import struct
import threading
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ConnectionTerminated, QuicEvent, StreamDataReceived
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509.oid import NameOID

# --- backend'den türetilen sabitler (istemciden BAĞIMSIZ yazıldı) -----------
AI_PROTOCOL = "hab/2"
"""`constant.rs:530`"""
AI_ALPN = "hab/2"
"""`constant.rs:531` — ALPN sürüm kapısı: farklı bir kimlik bildiren servis
TLS el sıkışmasında reddedilir."""
AI_MAX_FRAME_BYTES = 8 * 1024 * 1024
"""`constant.rs:536`"""
AI_IDLE_TIMEOUT_SECS = 30
"""`constant.rs:554`"""
CERTIFICATE_PATH = "/ai/certificate"
"""`src/web/ai.rs` — `certificate_pem` + `fingerprint_sha256`."""


# --- sertifika (backend'in `tls.rs:139-148` `self_signed`i) -----------------


@dataclass(frozen=True)
class Certificate:
    cert_pem: str
    key_pem: str
    fingerprint: str


def generate_certificate(names: tuple[str, ...] = ("localhost", "127.0.0.1")) -> Certificate:
    """Kendi kendine imzalı tek sertifika. CA DEĞİL: istemci onu güven
    deposuna PİNLEYEREK doğrular, zincir kurarak değil."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])
    now = datetime.datetime.now(datetime.timezone.utc)
    alt: list[x509.GeneralName] = []
    for name in names:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            alt.append(x509.DNSName(name))
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return Certificate(
        certificate.public_bytes(serialization.Encoding.PEM).decode("ascii"),
        key.private_bytes(encoding=serialization.Encoding.PEM,
                          format=serialization.PrivateFormat.PKCS8,
                          encryption_algorithm=serialization.NoEncryption()).decode("ascii"),
        # `tls.rs:150-153` ile aynı hesap: DER'in SHA-256'sı, küçük harf hex.
        hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest(),
    )


# --- çerçeveleme (`protocol.rs:267-304`: u32 BE uzunluk + JSON) -------------


def encode_frame(obj: Any) -> bytes:
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > AI_MAX_FRAME_BYTES:
        raise ValueError("çerçeve sınırı aşıldı")
    return struct.pack(">I", len(body)) + body


class _Reader:
    """Bir akışın gelen baytları: çerçeve okur."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._eof = False

    def feed(self, data: bytes, end: bool) -> None:
        if data:
            self._queue.put_nowait(data)
        if end:
            self._queue.put_nowait(None)

    async def _exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            if self._eof:
                raise EOFError("akış çerçeve tamamlanmadan bitti")
            chunk = await self._queue.get()
            if chunk is None:
                self._eof = True
                continue
            self._buf.extend(chunk)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    async def read_frame(self) -> Any:
        (length,) = struct.unpack(">I", await self._exact(4))
        if length > AI_MAX_FRAME_BYTES:
            raise ValueError(f"çerçeve sınırı aşıldı: {length}")
        return json.loads(await self._exact(length))


# --- bağlantı başına protokol ----------------------------------------------


class _Worker:
    """Kaydolmuş bir servis — backend'in `AiRegistry` kaydının küçüğü."""

    def __init__(self, worker_id: str, hello: dict, connection: "_Connection") -> None:
        self.worker_id = worker_id
        self.hello = hello
        self.connection = connection

    def open_stream(self) -> "_OutStream":
        """Sunucu başlatımlı YENİ bir akış aç (backend'in iş akışı).
        `sid % 4 == 1` olması bunun sunucu tarafı olduğunu söyler."""
        return self.connection.open_out_stream()

    async def call(self, capability: str, school: str, payload: Any,
                   deadline_ms: int = 30_000, timeout: float = 10.0) -> dict:
        """Bir `Request` gönder, tek `Response` oku (`server.rs:258-283`)."""
        stream = self.open_stream()
        request_id = f"FAKEREQ{self.connection.next_request_number():04d}"
        await stream.send({"id": request_id, "school": school,
                           "capability": capability, "deadline_ms": deadline_ms,
                           "payload": payload}, end=True)
        try:
            return await stream.read(timeout=timeout)
        finally:
            stream.close()


class _OutStream:
    """Sunucu başlatımlı tek bir akış: çerçeve yaz, çerçeve oku."""

    def __init__(self, connection: "_Connection", sid: int, reader: _Reader) -> None:
        self._connection = connection
        self.sid = sid
        self._reader = reader

    async def send(self, frame: Any, end: bool = True) -> None:
        self._connection.send(self.sid, frame, end)

    async def read(self, timeout: float = 5.0) -> Any:
        return await asyncio.wait_for(self._reader.read_frame(), timeout)

    def close(self) -> None:
        self._connection.forget(self.sid)


class _Connection(QuicConnectionProtocol):
    """Tek bir servis bağlantısı (`server.rs::serve_connection` karşılığı)."""

    def __init__(self, *args: Any, bridge: "FakeBridge", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._bridge = bridge
        self._readers: dict[int, _Reader] = {}
        self._control_sid: int | None = None
        self._tasks: set[asyncio.Future] = set()
        self._request_seq = 0
        self.worker: _Worker | None = None

    # -- olay dağıtımı --

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, StreamDataReceived):
            sid = event.stream_id
            reader = self._readers.get(sid)
            if reader is None:
                # Sunucu tarafında istemci başlatımlı çift yönlü akışlar
                # `sid % 4 == 0`; İLKİ kontrol akışıdır (`protocol.rs:11-14`).
                if sid % 4 != 0:
                    return
                reader = _Reader()
                self._readers[sid] = reader
                if self._control_sid is None:
                    self._control_sid = sid
                    self._spawn(self._serve_control(sid, reader))
                else:
                    self._spawn(self._serve_client_stream(sid, reader))
            reader.feed(event.data, event.end_stream)
        elif isinstance(event, ConnectionTerminated):
            for reader in self._readers.values():
                reader.feed(b"", end=True)
            if self.worker is not None:
                self._bridge.deregister(self.worker)
                self.worker = None

    def _spawn(self, coro: Any) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def send(self, sid: int, obj: Any, end: bool) -> None:
        self._quic.send_stream_data(sid, encode_frame(obj), end_stream=end)
        self.transmit()

    def forget(self, sid: int) -> None:
        self._readers.pop(sid, None)

    def next_request_number(self) -> int:
        self._request_seq += 1
        return self._request_seq

    def open_out_stream(self) -> _OutStream:
        sid = self._quic.get_next_available_stream_id(is_unidirectional=False)
        reader = _Reader()
        self._readers[sid] = reader
        return _OutStream(self, sid, reader)

    # -- kontrol akışı: `server.rs::register` --

    async def _serve_control(self, sid: int, reader: _Reader) -> None:
        try:
            hello = await reader.read_frame()
        except (EOFError, ValueError, json.JSONDecodeError) as exc:
            self._refuse(sid, "malformed", str(exc))
            return
        if not isinstance(hello, dict):
            self._refuse(sid, "malformed", "Hello bir nesne değil")
            return
        self._bridge.hellos.append(hello)

        # SIRA backend'inkiyle AYNI: sürüm, sonra token, sonra yetenekler
        # (`server.rs:949-991`). Sıra değişirse hangi redde uğradığı değişir.
        if hello.get("protocol") != AI_PROTOCOL:
            self._refuse(sid, "unsupported_protocol",
                         f"this backend speaks {AI_PROTOCOL}, the service "
                         f"announced {hello.get('protocol')}")
            return
        if str(hello.get("token", "")) != self._bridge.token:
            self._refuse(sid, "unauthorized", "invalid token")
            return
        capabilities = hello.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            self._refuse(sid, "no_capabilities", "declare at least one capability")
            return

        worker_id = f"FAKEWORKER{len(self._bridge.registrations) + 1:04d}"
        # `server.rs:1000-1008`: hoş geldin TELE ÇIKTIKTAN SONRA kaydedilir.
        self.send(sid, {"type": "welcome", "worker_id": worker_id,
                        "protocol": AI_PROTOCOL}, end=False)   # akış ömür boyu açık
        self.worker = _Worker(worker_id, hello, self)
        self._bridge.register(self.worker)

    def _refuse(self, sid: int, code: str, message: str) -> None:
        self._bridge.rejects.append(code)
        try:
            self.send(sid, {"type": "rejected", "code": code, "message": message},
                      end=True)
        except Exception:                              # noqa: BLE001
            pass

    # -- istemci başlatımlı akışlar --

    async def _serve_client_stream(self, sid: int, reader: _Reader) -> None:
        """Bugün istemci HİÇ akış açmaz (RAG yalnız `Request` cevaplar).

        Açarsa bu bir kayıttır: sunucu tipli bir red yazar ki bekleyen bir
        okuyucu asılı kalmasın."""
        try:
            raw = await reader.read_frame()
        except (EOFError, ValueError, json.JSONDecodeError) as exc:
            self._bridge.client_streams.append({"malformed": str(exc)})
            self.send(sid, _err("", "", "malformed", str(exc)), end=True)
            return
        self._bridge.client_streams.append(raw if isinstance(raw, dict) else {})
        self.send(sid, _err(str(raw.get("id") or ""), str(raw.get("school") or ""),
                            "malformed", "bu servis istemci akışı açmıyor"), end=True)


def _err(request_id: str, school: str, code: str, message: str) -> dict:
    return {"status": "err", "id": request_id, "school": school,
            "code": code, "message": message}


# --- sertifika HTTP ucu -----------------------------------------------------


class _CertificateHandler(BaseHTTPRequestHandler):
    payload = b""

    def do_GET(self) -> None:                          # noqa: N802 (stdlib adı)
        if self.path != CERTIFICATE_PATH:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args: Any) -> None:
        """Test çıktısını kirletmesin."""


# --- sunucu -----------------------------------------------------------------


class FakeBridge:
    """Ayağa kaldırılıp indirilebilen sahte bir köprü.

    `start()` iki soket açar: QUIC (UDP) ve sertifika için düz HTTP (TCP).
    İkisi de 127.0.0.1 üzerindedir ve `port` verilmezse işletim sisteminin
    verdiği boş port kullanılır — dışarıya HİÇBİR bağlantı kurulmaz."""

    def __init__(self, *, port: int = 0, token: str = "test-token") -> None:
        self.token = token
        self.certificate = generate_certificate()
        #: Şu an kayıtlı worker'lar; bağlantı kopunca küçülür.
        self.workers: list[_Worker] = []
        #: Şimdiye kadar kaydolmuş HER worker; asla küçülmez.
        self.registrations: list[_Worker] = []
        #: Gelen her `Hello` (sırayla).
        self.hellos: list[dict] = []
        #: El sıkışma ret kodları.
        self.rejects: list[str] = []
        #: İstemcinin açtığı (kontrol dışı) akışların çerçeveleri.
        self.client_streams: list[dict] = []
        self._port = port
        self._server: Any = None
        self._quic_config: Any = None
        self.close_quic_port: int = 0
        self._http: ThreadingHTTPServer | None = None
        self._http_thread: Any = None
        self._connections: set[_Connection] = set()
        self._worker_event = asyncio.Event()

    # -- yaşam döngüsü --

    async def start(self) -> None:
        quic_config = QuicConfiguration(is_client=False, alpn_protocols=[AI_ALPN],
                                        idle_timeout=AI_IDLE_TIMEOUT_SECS)
        # `load_cert_chain()` yalnız DOSYADAN okur; alanlar doğrudan doldurulur.
        chain = x509.load_pem_x509_certificates(self.certificate.cert_pem.encode("ascii"))
        quic_config.certificate = chain[0]
        quic_config.certificate_chain = chain[1:]
        # `password=None` AÇIKÇA verilir: `cryptography` 50'de parametre
        # zorunludur (kardeş servisin dosyası eski sürümde yazılmıştı).
        quic_config.private_key = load_pem_private_key(
            self.certificate.key_pem.encode("ascii"), password=None)
        self._quic_config = quic_config
        await self._bind_quic(self._port)
        self._start_http()

    async def _bind_quic(self, port: int) -> None:
        self._server = await serve(
            "127.0.0.1", port, configuration=self._quic_config,
            create_protocol=partial(_Connection, bridge=self))

    def close_quic(self) -> None:
        """YALNIZ QUIC sunucusunu kapat (backend'in QUIC'i düşük, sertifika
        HTTP ucu ayakta senaryosu). Port serbest kalır; `reopen_quic()` AYNI
        portu geri alabilir — bu, `wait_for_worker`ın "backend geri geldi"
        anını beklemesini sağlar (boş bir portu başkasının kapması yarışı
        olmadan)."""
        if self._server is not None:
            self.close_quic_port = self.quic_port
            self._server.close()
            self._server = None

    async def reopen_quic(self) -> None:
        await self._bind_quic(self.close_quic_port)

    def _start_http(self) -> None:
        body = json.dumps({"certificate_pem": self.certificate.cert_pem,
                           "fingerprint_sha256": self.certificate.fingerprint}
                          ).encode("utf-8")
        handler = type("_Handler", (_CertificateHandler,), {"payload": body})
        self._http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._http_thread = threading.Thread(target=self._http.serve_forever,
                                             daemon=True)
        self._http_thread.start()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._http is not None:
            http, thread = self._http, self._http_thread
            self._http, self._http_thread = None, None

            def _kapat() -> None:
                http.shutdown()
                http.server_close()
                if thread is not None:
                    thread.join(timeout=5)

            # Kapanışı ayrı bir iş parçacığında bekle: `shutdown()` sunucu
            # döngüsünün durmasını bekler, olay döngüsünde beklemek kilitlenir.
            await asyncio.get_running_loop().run_in_executor(None, _kapat)
        await asyncio.sleep(0)          # kapanış datagramları yollansın

    # -- adresler --

    @property
    def quic_port(self) -> int:
        sock = self._server._transport.get_extra_info("socket")
        return int(sock.getsockname()[1])

    @property
    def http_port(self) -> int:
        assert self._http is not None
        return int(self._http.server_address[1])

    @property
    def backend_url(self) -> str:
        return f"http://127.0.0.1:{self.http_port}"

    # -- kayıt defteri --

    def register(self, worker: _Worker) -> None:
        self.workers.append(worker)
        self.registrations.append(worker)
        self._connections.add(worker.connection)
        self._worker_event.set()

    def deregister(self, worker: _Worker) -> None:
        self._connections.discard(worker.connection)
        self.workers = [w for w in self.workers if w.worker_id != worker.worker_id]
        if not self.workers:
            self._worker_event.clear()

    async def wait_for_worker(self, timeout: float = 10.0) -> _Worker:
        """Bir servis kaydolana kadar bekle.

        KOPMADAN SONRA ÇAĞRILIRSA yeni kaydı bekler: `drop_connections()`
        defteri hemen boşalttığı için yarış yok."""
        await asyncio.wait_for(self._worker_event.wait(), timeout=timeout)
        return self.workers[-1]

    def drop_connections(self) -> None:
        """Kayıtlı her bağlantıyı kopar — backend'in çökmesini taklit eder.

        Defter HEMEN boşaltılır: `ConnectionTerminated` olayının gelmesini
        beklemek, `wait_for_worker`ın eski worker'ı döndürdüğü bir yarış
        yaratırdı."""
        for connection in list(self._connections):
            connection.close()
            connection.transmit()
        self._connections.clear()
        self.workers.clear()
        self._worker_event.clear()

    async def call(self, capability: str, school: str, payload: Any,
                   deadline_ms: int = 30_000, timeout: float = 10.0) -> dict:
        """Kayıtlı son worker'a sunucu başlatımlı bir istek yolla."""
        return await self.workers[-1].call(capability, school, payload,
                                           deadline_ms=deadline_ms, timeout=timeout)
