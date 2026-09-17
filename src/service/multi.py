"""Çok-korpus servisi (#86 kayıt defterini ÜRÜNE bağlar).

ÖLÇÜLEN DURUM: `CorpusRegistry` yazıldı ve test edildi ama `http_app`'e HİÇ
BAĞLANMADI. Servis hâlâ tek `BOOK_PATH` okuyor. Elimizde 15 kitap var (lise
10, 15 ders) ve ürün yalnız birine cevap veriyor.

ÜRÜN AÇISINDAN NE DEMEK: okul demosunda öğrenci kimyaya geçtiği anda ürün
"kaynaklarda bulunamadı" diyor. Bu bir RAG hatası gibi görünür ama aslında
**o korpus hiç yüklü değildir**. Demoyu izleyen öğretmen için ürün "yalnız
biyoloji biliyor" demektir.

İKİ ÖLÇÜLMÜŞ KISIT bu tasarımı belirledi:

1. MODELLER PAYLAŞILMALI. `build_service` her çağrıda kendi embedder ve
   reranker'ını kuruyordu: 15 kitap × (2,3 GB + 2,3 GB) → 8 GB GPU'da OOM.
   `SharedModels` bunu tek örneğe indiriyor; indeksler korpusa özel kalıyor.

2. TEMBEL YÜKLEME ŞART. Tek kitabın indeksi GPU'da 47,6 s kuruluyor
   (CPU'da 548 s). 15 kitabı açılışta kurmak ~12 dakikalık sağır servis
   demekti — ve indeks kalıcı olmadığı için (#75) bu bedel HER yeniden
   başlatmada ödenirdi. Korpus, o derse ilk soru geldiğinde kurulur.

   DÜRÜST SINIR: bir dersin İLK sorusu yavaştır (~48 s). Bunu gizlemiyoruz;
   `/ready` hangi korpusların hazır olduğunu söyler ve `warm()` ile demo
   öncesi ısıtılabilir.
"""
from __future__ import annotations

import os
import threading
import time

from .registry import CorpusRegistry
from .handler import scope_pairs

# Yüklenecek korpuslar: "sinif/ders" listesi, virgülle.
#   RAG_CORPORA=10/biyoloji,10/kimya,10/fizik
CORPORA = [p.strip() for p in os.environ.get("RAG_CORPORA", "").split(",")
           if p.strip()]
CORPUS_ROOT = os.environ.get("RAG_CORPUS_ROOT", "data")
CORPUS_KASA = os.environ.get("RAG_CORPUS_KASA", "lise")
# Bellek valfi: #75 (kalıcı store) çözülene kadar RSS korpus sayısıyla
# lineer büyür. 0 = sınırsız.
MAX_CORPORA = int(os.environ.get("RAG_MAX_CORPORA", "0") or 0)
# Açılışta ısıtılacaklar: "" = hiçbiri (tamamen tembel), "all" = hepsi.
WARM_ON_START = os.environ.get("RAG_WARM_CORPORA", "").strip()


def book_path(sinif: str, ders: str, *, root: str | None = None,
              kasa: str | None = None) -> str:
    return os.path.join(root or CORPUS_ROOT, kasa or CORPUS_KASA,
                        str(sinif), str(ders), "kitap.pdf")


def discover(root: str | None = None, kasa: str | None = None) -> list:
    """Diskteki `(sinif, ders)` çiftlerini bulur. Sıralı ve deterministik."""
    kok = os.path.join(root or CORPUS_ROOT, kasa or CORPUS_KASA)
    out = []
    if not os.path.isdir(kok):
        return out
    for sinif in sorted(os.listdir(kok)):
        d = os.path.join(kok, sinif)
        if not os.path.isdir(d):
            continue
        for ders in sorted(os.listdir(d)):
            if os.path.isfile(os.path.join(d, ders, "kitap.pdf")):
                out.append((sinif, ders))
    return out


def _parse(spec: str) -> tuple:
    """"10/biyoloji" → ("10", "biyoloji")."""
    parca = [p for p in spec.split("/") if p]
    if len(parca) != 2:
        raise ValueError(f"korpus tanimi 'sinif/ders' olmali: {spec!r}")
    return parca[0], parca[1]


class MultiCorpusService:
    """Birden çok korpusa hizmet eden `RagService` cephesi.

    `chat`/`summarize`/`generate_questions` imzaları tek-korpus servisle
    AYNIDIR; `create_app` ikisini de kabul eder.

    YÖNLENDİRME YETKİLENDİRME DEĞİLDİR: burada yalnız "hangi kitap" sorusu
    cevaplanır. "Bu öğrenci onu görebilir mi" sorusunu alt servisin kendi
    `guard/roles.can_access` kontrolü cevaplar ve o kontrol KALDIRILMADI.
    """

    def __init__(self, specs=None, *, shared=None, root: str | None = None,
                 kasa: str | None = None, max_corpora: int | None = None,
                 builder=None):
        from .http_app import SharedModels, build_service
        self.root = root or CORPUS_ROOT
        self.kasa = kasa or CORPUS_KASA
        self.shared = shared if shared is not None else SharedModels()
        self._build = builder if builder is not None else build_service
        self.registry = CorpusRegistry(
            max_corpora=MAX_CORPORA if max_corpora is None else max_corpora)
        self._specs = {}
        for spec in (specs if specs is not None else CORPORA):
            sinif, ders = _parse(spec) if isinstance(spec, str) else spec
            self._specs[(str(sinif), str(ders))] = book_path(
                sinif, ders, root=self.root, kasa=self.kasa)
        self._locks: dict = {}
        self._lock = threading.Lock()
        # KOSARAK BULUNDU: iki korpus AYNI ANDA kurulunca surec SEGFAULT ile
        # coktu. Sebep paylasimli BGE-M3 ornegini iki thread'den es zamanli
        # `encode()` etmek -- FlagEmbedding/torch bu kullanimda guvenli degil
        # ve ayrica iki indeks kurulumu VRAM tepesini ikiye katliyor (8 GB).
        # Kurulumlar bu kilitle SIRAYA sokulur; sorgular etkilenmez (onlar
        # kurulmus indeksleri kullanir).
        self._build_gate = threading.Lock()
        self._load_errors: dict = {}
        self._building: set = set()

    # -- korpus yaşam döngüsü -------------------------------------------
    def known(self) -> list:
        return sorted(self._specs)

    def loaded(self) -> list:
        return [(k.sinif, k.ders) for k in self.registry.keys()]

    def _key_lock(self, key):
        """Korpus başına kilit. #80'in dersi: kilitsiz tembel yükleme, 8
        eşzamanlı istekte 8 paralel indeks kurulumu demekti."""
        with self._lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    def ensure(self, sinif: str, ders: str, *, block: bool = True):
        """Korpusu (gerekirse) kurar ve servisi döndürür.

        `block=False`: kurulum ARKA PLANDA başlatılır ve hemen None döner.

        KOŞULARAK BULUNDU: soğuk bir dersin ilk sorusu korpus kurulurken
        (GPU'da ~48 s, CPU'da ~550 s) istek son tarihini (60 s) aşıyor ve
        istemci **HTTP 504** alıyordu. Yani öğrenci kimyaya geçtiği anda
        zaman aşımı görüyordu — demoyu kıran davranış. Artık ürün hemen
        "hazırlanıyor, birazdan tekrar dene" der (`service_warming_up`,
        API-CONTRACT #82) ve kurulum arkada sürer.
        """
        key = (str(sinif), str(ders))
        mevcut = self.registry.get(*key)
        if mevcut is not None:
            return mevcut
        yol = self._specs.get(key)
        if yol is None or not os.path.isfile(yol):
            return None
        if not block:
            with self._lock:
                if key in self._building or key in self._load_errors:
                    return None
                self._building.add(key)
            threading.Thread(target=self._build_bg, args=(key, yol),
                             name=f"korpus-{key[0]}-{key[1]}",
                             daemon=True).start()
            return None
        with self._key_lock(key):
            mevcut = self.registry.get(*key)         # kilit içinde tekrar bak
            if mevcut is not None:
                return mevcut
            if key in self._load_errors:
                # Bozuk bir korpusu her istekte yeniden kurmaya çalışmak,
                # servisi o ders sorulduğunda kilitlerdi.
                return None
            t0 = time.time()
            try:
                with self._build_gate:       # korpus kurulumlari SERI
                    svc = self._build(yol, sinif=key[0], ders=key[1],
                                      shared=self.shared)
            except Exception as e:                            # noqa: BLE001
                self._load_errors[key] = f"{type(e).__name__}: {e}"
                print(f"[korpus][HATA] {key[0]}/{key[1]}: {e}", flush=True)
                return None
            try:
                self.registry.register(svc, sinif=key[0], ders=key[1])
            except ValueError as e:
                # Korpus siniri bilincli bir bellek valfi (#75 cozulene kadar
                # RSS lineer buyur). Asildiginda ISTISNA YUKARI SIZMAMALI:
                # ogrenciye 500 donmek yerine tipli bir red uretilir.
                self._load_errors[key] = f"limit: {e}"
                print(f"[korpus][SINIR] {key[0]}/{key[1]}: {e}", flush=True)
                return None
            print(f"[korpus] {key[0]}/{key[1]} hazir ({time.time() - t0:.1f}s)",
                  flush=True)
            return svc

    def _build_bg(self, key, yol) -> None:
        try:
            self.ensure(key[0], key[1], block=True)
        finally:
            with self._lock:
                self._building.discard(key)

    def building(self) -> list:
        with self._lock:
            return sorted(f"{a}/{b}" for a, b in self._building)

    def warm(self, specs=None) -> dict:
        """Verilen korpusları önceden kurar (demo öncesi ısıtma)."""
        hedef = specs if specs is not None else self.known()
        out = {}
        for sinif, ders in hedef:
            out[f"{sinif}/{ders}"] = self.ensure(sinif, ders) is not None
        return out

    # -- yönlendirme -----------------------------------------------------
    def _route(self, req: dict):
        """(service, reason). Yüklü değilse kurmayı DENER."""
        svc, sebep = self.registry.resolve(req)
        if svc is not None:
            return svc, ""
        if sebep == "corpus_ambiguous":
            return None, sebep
        rol = req.get("role") or {}
        raw_scope = req.get("scope")
        # YENİ rag.chat biçimi: çift listesi. Eski sözlük/sinif+ders_list yolu
        # (`else`) AYNEN kalır (geriye uyum).
        pairs = scope_pairs(raw_scope) if isinstance(raw_scope, (list, tuple)) else []
        if pairs:
            if len(pairs) == 1:
                sinif, ders = pairs[0]
            else:
                adaylar = [(s, d) for (s, d) in pairs
                           if (str(s), str(d)) in self._specs]
                if len(adaylar) == 1:
                    sinif, ders = adaylar[0]
                else:
                    return None, "corpus_ambiguous"
        else:
            scope = raw_scope if isinstance(raw_scope, dict) else {}
            sinif = scope.get("sinif") or rol.get("sinif")
            ders = scope.get("ders") or (req.get("options") or {}).get("ders")
            if not ders:
                dersler = list(rol.get("ders_list") or [])
                # Tek ders taşıyorsa belirsizlik yok; birden fazlaysa BİLİNEN
                # korpuslarla kesiştir — tek aday kalıyorsa onu kur.
                adaylar = [d for d in dersler
                           if (str(sinif), str(d)) in self._specs]
                if len(dersler) == 1:
                    ders = dersler[0]
                elif len(adaylar) == 1:
                    ders = adaylar[0]
                elif adaylar:
                    return None, "corpus_ambiguous"
        if not sinif or not ders:
            return None, "no_corpus"
        # Yapilandirmada YAZAN ama diskte OLMAYAN kitap "hazirlaniyor" demez:
        # o korpus asla hazir olmayacagi icin istemci sonsuza kadar yeniden
        # denerdi. Dosya yoksa bu bir NO_CORPUS'tur.
        yol = self._specs.get((str(sinif), str(ders)))
        if yol is None or not os.path.isfile(yol):
            return None, "no_corpus"
        svc = self.ensure(sinif, ders, block=False)
        if svc is not None:
            return svc, ""
        if (str(sinif), str(ders)) in self._load_errors:
            return None, "no_corpus"
        return None, "service_warming_up"

    def _refused(self, sebep: str, kind: str) -> dict:
        metin = {"no_corpus": NO_CORPUS_TEXT,
                 "corpus_ambiguous": AMBIGUOUS_TEXT,
                 "service_warming_up": WARMING_TEXT}.get(sebep, NO_CORPUS_TEXT)
        ortak = {"text": metin, "abstained": True, "reason": sebep,
                 "cost_usd": 0.0}
        if kind == "chat":
            return {**ortak, "citations": [], "used_source_ids": [],
                    "invalid_citations": [], "cache_hit": False}
        if kind == "ozet":
            return {**ortak, "citations": [], "scope_pages": [],
                    "hierarchical": False}
        return {**ortak, "items": [], "span_ids": [], "pages": []}

    def chat(self, req: dict) -> dict:
        svc, sebep = self._route(req)
        return svc.chat(req) if svc is not None else self._refused(sebep, "chat")

    def summarize(self, req: dict) -> dict:
        svc, sebep = self._route(req)
        return (svc.summarize(req) if svc is not None
                else self._refused(sebep, "ozet"))

    def generate_questions(self, req: dict) -> dict:
        svc, sebep = self._route(req)
        return (svc.generate_questions(req) if svc is not None
                else self._refused(sebep, "soru"))

    # -- gözlem ----------------------------------------------------------
    @property
    def generator(self):
        """`/ready` "generator var mı" diye bakıyor. Çok-korpusta hazır olmak
        = EN AZ BİR korpus yüklü ya da yüklenebilir olmak."""
        for k in self.registry.keys():
            svc = self.registry.get(k.sinif, k.ders)
            g = getattr(svc, "generator", None)
            if g is not None:
                return g
        return object() if self._specs else None

    @property
    def doc(self):
        for k in self.registry.keys():
            d = getattr(self.registry.get(k.sinif, k.ders), "doc", None)
            if d is not None:
                return d
        return None

    def status(self) -> dict:
        s = self.registry.stats()
        # Anahtarlar METIN olmali: `/ready` bu sozlugu JSON'a cevirir ve
        # tuple anahtar serilesmez (uc noktayi 500'e dusururdu).
        return {"bilinen": [f"{a}/{b}" for a, b in self.known()],
                "yuklu": [f"{a}/{b}" for a, b in self.loaded()],
                "kuruluyor": self.building(),
                "chunk": s.chunks,
                "hatalar": {f"{a}/{b}": v
                            for (a, b), v in self._load_errors.items()}}


NO_CORPUS_TEXT = ("Bu ders için kaynak yüklü değil. Öğretmenine sorabilir ya da "
                  "başka bir ders seçebilirsin.")
AMBIGUOUS_TEXT = "Hangi ders için sorduğunu anlayamadım. Dersi seçer misin?"
WARMING_TEXT = ("Bu dersin kaynakları hazırlanıyor, birazdan tekrar dener "
                "misin?")
