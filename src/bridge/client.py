"""Backend'den okuma istemcileri — üçü de aynı `.get()` arayüzünü sunar.

Neden üç tane:
  * `BridgeReader`  — gerçek yol. hab/2 üzerinden `ApiRequest` yazar. Taşıma
    (QUIC akışı) DIŞARIDAN verilir; bu sınıf yalnız çerçeveyi kurar ve cevabı
    çözer, böylece ağ olmadan da test edilir.
  * `RestReader`   — backend'in REST'ine doğrudan HTTP. Tohumlama ve elle
    doğrulama için (Kadir giriş yapabiliyor). Köprü ayakta olmasa da çalışır.
  * `FakeReader`  — sabit sözlükten okur. Testler ve senaryo üretimi.

Üçü de aynı sözleşmeyi tutar: `get(path, *, query=None, on_behalf_of=None)`
→ `(status, body)`. Böylece `ogrenci.build_context` hangi taşımayla koştuğunu
BİLMEZ; ayrışma olamaz.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .contract import ApiRequest, decode_api_response


class BridgeReader:
    """hab/2 `ApiRequest` ile okur.

    `akis_ac`: çağrıldığında `(gonder, al)` çifti döndüren bir fonksiyon —
    `gonder(dict)` bir çerçeve yazar, `al() -> dict` tek cevabı okur. QUIC
    ayrıntısı bu sınıfın DIŞINDADIR (backend'in kendi ifadesiyle: her okuma
    "its own client-initiated bidirectional stream" üzerinde).
    """

    def __init__(self, akis_ac, *, school: str):
        self._akis_ac = akis_ac
        self.school = school

    def get(self, path: str, *, query: str | None = None,
            on_behalf_of: str | None = None) -> tuple[int, object]:
        istek = ApiRequest(id=uuid.uuid4().hex.upper()[:26], school=self.school,
                           path=path, query=query, on_behalf_of=on_behalf_of)
        gonder, al = self._akis_ac()
        gonder(istek.to_wire())
        return decode_api_response(al())


class RestReader:
    """Doğrudan HTTP. Oturum çerezi (`session`) ile koşar.

    DÜRÜST SINIR: bu yol `on_behalf_of` TAŞIMAZ — HTTP'de kim giriş yaptıysa
    o okur. `on_behalf_of` verilip de oturum sahibi başka biriyse **hata
    fırlatır**; sessizce yanlış kullanıcının verisini döndürmek, kasa
    izolasyonunu ölçtüğümüz her şeyi geçersiz kılardı.
    """

    def __init__(self, base_url: str, *, school: str, session_token: str,
                 own_user_id: str | None = None, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.school = school
        self.session_token = session_token
        self.own_user_id = own_user_id
        self.timeout = timeout

    def get(self, path: str, *, query: str | None = None,
            on_behalf_of: str | None = None) -> tuple[int, object]:
        if on_behalf_of is not None and self.own_user_id is not None \
                and on_behalf_of != self.own_user_id:
            raise ValueError(
                "RestReader baskasi adina okuyamaz: oturum "
                f"{self.own_user_id}, istenen {on_behalf_of}. Kopru (hab/2) kullan.")
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Cookie", f"session={self.school}.{self.session_token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            govde = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(govde or "null")
            except json.JSONDecodeError:
                return e.code, govde


class FakeReader:
    """Sabit yanıt tablosundan okur — ağ YOK.

    Anahtar: `(path, query)`; `query=None` her sorguya uyan yedek kayıttır.
    `on_behalf_of` kaydedilir ki testler "öğrenci ADINA mı okundu" diye
    doğrulayabilsin (yetkiyi backend uyguluyor; biz doğru kimliği geçtiğimizi
    ölçeriz).
    """

    def __init__(self, tablo: dict, *, varsayilan: tuple[int, object] = (404, None)):
        self.tablo = tablo
        self.varsayilan = varsayilan
        self.calls: list[tuple[str, str | None, str | None]] = []

    def get(self, path: str, *, query: str | None = None,
            on_behalf_of: str | None = None) -> tuple[int, object]:
        self.calls.append((path, query, on_behalf_of))
        if (path, query) in self.tablo:
            return self.tablo[(path, query)]
        if (path, None) in self.tablo:
            return self.tablo[(path, None)]
        return self.varsayilan

    @classmethod
    def from_snapshot(cls, yol: str) -> "FakeReader":
        """`outputs/ogrenci-senaryosu/*.json` dosyasından okuyucu kurar."""
        with open(yol, encoding="utf-8") as fh:
            veri = json.load(fh)
        tablo: dict = {}
        for kayit in veri["responses"]:
            tablo[(kayit["path"], kayit.get("query"))] = (kayit["status"], kayit["body"])
        return cls(tablo)


def login(base_url: str, *, school: str, username: str, password: str,
              timeout: float = 15.0) -> str:
    """`POST /auth/login` → oturum jetonu (`<school>.<token>` çerezinin jeton yarısı).

    Backend çerezi `<school>.<token>` biçiminde verir (`web/auth.rs`): bir
    kullanıcı adı ancak okuluyla BİRLİKTE bir hesabı tanımlar.
    """
    govde = json.dumps({"school": school, "username": username,
                        "password": password}).encode("utf-8")
    req = urllib.request.Request(f"{base_url.rstrip('/')}/auth/login", data=govde,
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        cerez = r.headers.get("Set-Cookie") or ""
    for parca in cerez.split(";"):
        parca = parca.strip()
        if parca.startswith("session="):
            deger = parca[len("session="):]
            return deger.split(".", 1)[1] if "." in deger else deger
    raise ValueError("giris basarili ama `session` cerezi yok")


def reader_from_env():
    """Env'den bir okuyucu kurar; eksikse None (çağıran senaryoya düşer).

    HEZARFEN_BACKEND_URL, HEZARFEN_SCHOOL, HEZARFEN_USER, HEZARFEN_PASS
    """
    url = os.environ.get("HEZARFEN_BACKEND_URL")
    okul = os.environ.get("HEZARFEN_SCHOOL")
    kul = os.environ.get("HEZARFEN_USER")
    sifre = os.environ.get("HEZARFEN_PASS")
    if not (url and okul and kul and sifre):
        return None
    jeton = login(url, school=okul, username=kul, password=sifre)
    return RestReader(url, school=okul, session_token=jeton)
