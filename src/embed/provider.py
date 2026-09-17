"""Gömme (embedding) sağlayıcı seçimi: yerel model ↔ uzak API.

NEDEN: yerel BGE-M3 sorgu anında ucuz (CPU'da 0,122 s) ama **indeks kurulumu**
CPU'da 548 s sürüyor (GPU'da 47,6 s) ve indeks bellekte olduğu için bu bedel
her yeniden başlatmada ödeniyor (#75). Uzak API bu iki maliyeti de ortadan
kaldırır; karşılığında ağa bağımlılık ve sorgu başına ücret getirir.

SEÇİM `RAG_EMBED_PROVIDER` ile yapılır: `local` (varsayılan) | `api` | `cohere`
| `voyage`.

`voyage` (dağıtım seçimi, 2026-09-17): taşıma OpenAI yoluyla BİREBİR aynıdır
(`{RAG_EMBED_API_BASE}/embeddings`, vektörler `data[].embedding`); tek fark
`input_type` sözlüğüdür — Voyage `passage`ı REDDEDİYOR (ölçüldü: 400 "Value
'passage' supplied for argument 'input_type' is not valid -- accepted values are
'query' or 'document'"). rag'in `passage` niyeti `document` olarak gider.

`cohere` NEDEN AYRI BİR YOL (ölçüldü 2026-09-17): Cohere'in OpenAI-uyumluluk
katmanı `input_type` alanını REDDEDİYOR (`POST /compatibility/v1/embeddings` +
`input_type=search_query` → 422 "search_query input type is not supported for
this model"; alanı düşürünce 200 döner). Yani uyumluluk katmanı, v3
modellerinin ihtiyaç duyduğu SORU/PASAJ ayrımını sessizce kaybettirirdi —
retrieval kalitesini belirleyen tam da o alan. Native `POST /v2/embed`
`input_type`ı kabul eder ve vektörleri `embeddings.float` altında döndürür.

=== API'YE GEÇMENİN ÖLÇÜLMÜŞ BEDELLERİ (sessizce yaşanmasın diye yazılı) ===

1. SPARSE VEKTÖR KAYBOLUR. BGE-M3 dense + sparse'ı TEK geçişte üretir; hibrit
   retrieval üç ayağa dayanır: dense (anlam) + BM25 (köksüz lexical) + sparse
   (öğrenilmiş lexical). OpenAI-uyumlu `/v1/embeddings` uçları **yalnız dense**
   döndürür. Yani API'ye geçmek retrieval'ın bir ayağını keser — BM25 kalır ama
   sparse gider. Bu kod o kaybı SESSİZCE yaşamaz: `sparse_supported=False`
   döner ve çağıran katman uyarır.

2. ÖLÇÜLMÜŞ KALİTE SAYILARI GEÇERSİZ OLUR. Golden set üzerindeki bütün
   ölçümler (EXP-011/013/017/018) BGE-M3 ile alındı. Başka bir gömme modeli
   başka bir vektör uzayıdır; recall/nDCG sayıları o modele ait DEĞİLDİR ve
   yeniden ölçülmelidir.

3. İNDEKS GEÇERSİZ OLUR. Farklı model = farklı boyut ve farklı uzay. Eski
   vektörlerle yeni sorgu vektörünü karşılaştırmak anlamsız sonuç üretir —
   `corpus_version` değişmeli ve indeks yeniden kurulmalıdır. Boyut uyuşmazlığı
   burada AÇIKÇA hata verir; sessizce yanlış sonuç döndürmez.

4. GEÇİT 2xx GÖVDESİNDE HATA DÖNDÜREBİLİR (Kilo/OpenRouter, yük altında HTTP
   200 + `{"error":{"code":503,...}}`). Bu kod onu "beklenmeyen yanıt" diye
   okumaz: geçici kodu yeniden dener, kalıcı kodda sağlayıcının KENDİ mesajıyla
   İLK denemede biter.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

import numpy as np

from ..providers.resilience import (RETRYABLE_STATUS, backoff_delay,
                                    provider_error_from_body)

PROVIDER = os.environ.get("RAG_EMBED_PROVIDER", "local").strip().lower()
API_BASE = os.environ.get("RAG_EMBED_API_BASE", "").rstrip("/")
API_MODEL = os.environ.get("RAG_EMBED_MODEL", "")
API_KEY_ENV = os.environ.get("RAG_EMBED_API_KEY_ENV", "RAG_EMBED_API_KEY")
API_TIMEOUT = float(os.environ.get("RAG_EMBED_TIMEOUT_S", "30"))
API_BATCH = int(os.environ.get("RAG_EMBED_BATCH", "32"))

#: Geçici sayılan bir hata (2xx gövdesindeki geçici kod ya da 429/5xx durum
#: kodu) için toplam deneme sayısı. Kalıcı hatalar İLK denemede biter.
CALL_ATTEMPTS = 3

#: İndeksin beklediği vektör boyutu (tek kaynak: `src/index/dense.py` içindeki
#: `DenseIndex(dim=...)` varsayılanı = 1024). DEĞİŞMEZ: modeli 384 boyutlu
#: `light` varyantına çevirmek eski 1024'lük vektörlerle aynı indekse karışır
#: ve arama sessizce bozulur. Farklı boyutlu bir modele gerçekten geçilecekse
#: bu sabit + `DenseIndex` boyutu birlikte değişir ve korpus yeniden indekslenir.
INDEX_DIM = 1024

#: Cohere v3 ailesinin YAYINLANMIŞ boyutları. Ölçüm tek kaynak olmaya devam
#: eder (aşağıda karşılaştırılır); bu tablo, uyuşmazlığı AĞA ÇIKMADAN ve model
#: ADIYLA söyleyebilmek içindir. Tanınmayan modelde yalnız ölçüm geçerlidir.
COHERE_MODEL_DIMS = {
    "embed-multilingual-v3.0": 1024,
    "embed-multilingual-light-v3.0": 384,
    "embed-english-v3.0": 1024,
    "embed-english-light-v3.0": 384,
}

#: rag'in KENDİ input-type niyeti (`query`/`passage`) → Cohere'in sözlüğü.
#: Eşleme burada; çağıran katman (retriever/generator) kendi niyetini değiştirmez.
COHERE_INPUT_TYPES = {"query": "search_query", "passage": "search_document"}

#: Voyage'ın sözlüğü: `passage` KABUL EDİLMEZ (ölçüldü 2026-09-17: 400
#: "Value 'passage' supplied for argument 'input_type' is not valid -- accepted
#: values are 'query' or 'document'"). Aksi hâlde her indeks kurulumu 400 düşer.
VOYAGE_INPUT_TYPES = {"query": "query", "passage": "document"}

#: Voyage'ın ÖLÇÜLEN boyutu (voyage-multilingual-2 → 1024, 2026-09-17 canlı).
#: Tanınmayan Voyage modeli tabloda yoktur; yine de ölçülen boyut indeksin
#: boyutuyla karşılaştırılır (kapı yalnız mesajı zenginleştirir).
VOYAGE_MODEL_DIMS = {"voyage-multilingual-2": 1024}


class EmbeddingUnavailable(RuntimeError):
    """Gömme sağlayıcısına ulaşılamıyor.

    `LlmUnavailable` ile aynı ruhta ama AYRI bir tip: gömme çökerse retrieval
    HİÇ çalışmaz (LLM çökerse yalnız üretim durur, arama yine yapılabilirdi).
    İkisini aynı tipe indirmek, olay incelemesinde yanlış katmana bakmak olurdu.
    """


class ApiEmbedder:
    """OpenAI-uyumlu `/v1/embeddings` istemcisi.

    DÜRÜST SINIR: `sparse_supported = False`. `embed_sparse()` çağrılırsa boş
    ağırlık döndürür (istisna DEĞİL — hibrit retriever sparse'ı opsiyonel
    kullanır), ama `sparse_supported` bayrağı çağıranın bunu bilmesini sağlar.
    """

    sparse_supported = False

    def __init__(self, *, base_url: str | None = None, model: str | None = None,
                 api_key: str | None = None, timeout: float | None = None,
                 batch_size: int | None = None, dim: int | None = None):
        self.base_url = (base_url if base_url is not None else API_BASE).rstrip("/")
        self.model_name = model if model is not None else API_MODEL
        self.timeout = API_TIMEOUT if timeout is None else float(timeout)
        self.batch_size = API_BATCH if batch_size is None else int(batch_size)
        self._key = api_key if api_key is not None else os.environ.get(API_KEY_ENV, "")
        self._dim = dim
        if not self.base_url or not self.model_name:
            raise ValueError(
                "API gomme icin RAG_EMBED_API_BASE ve RAG_EMBED_MODEL gerekli")

    @property
    def dim(self) -> int:
        """Boyut ilk çağrıda ÖLÇÜLÜR, varsayılmaz.

        Sabit bir sayı yazmak (ör. 1024) yanlış modelde sessizce bozuk indeks
        üretirdi; indeks boyutu ilk gerçek yanıttan öğrenilir.
        """
        if self._dim is None:
            self._dim = len(self._call(["boyut olcumu"], "passage")[0])
        return int(self._dim)

    #: Sağlayıcının `input_type` sözlüğü. BOŞ = "AYNEN gönder" (OpenAI-uyumlu
    #: `api` yolu: sorgu/pasaj adlarını sağlayıcı nasıl istiyorsa öyle).
    #: Voyage `passage`ı REDDEDİYOR, Cohere bambaşka iki ad istiyor; eşleme
    #: sağlayıcı SINIFINDA durur, çağıran katman kendi niyetini korur.
    INPUT_TYPES: dict = {}

    def _input_type(self, input_type: str) -> str:
        """rag'in niyeti (`query`/`passage`) → sağlayıcının kabul ettiği ad."""
        return self.INPUT_TYPES.get(input_type, input_type)

    def _call(self, texts: list[str], input_type: str) -> list:
        govde = {"model": self.model_name, "input": list(texts),
                 "encoding_format": "float"}
        # NVIDIA NIM ve Cohere `input_type` ister (query/passage ayrimi retrieval
        # kalitesini belirgin degistirir); OpenAI yok sayar. Gondermek guvenli.
        # `api` yolunda `_input_type` AYNI dizeyi döndürür (gövde değişmez).
        govde["input_type"] = self._input_type(input_type)
        istek = urllib.request.Request(
            f"{self.base_url}/embeddings", data=json.dumps(govde).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self._key}"} if self._key else {})})
        deneme = 0
        while True:
            deneme += 1
            try:
                with urllib.request.urlopen(istek, timeout=self.timeout) as yanit:
                    veri = json.loads(yanit.read())
            except urllib.error.HTTPError as e:
                # GERCEK DURUM KODU tasiyan hata (429/5xx gecici sayilir).
                govde_metni = ""
                try:
                    govde_metni = e.read().decode("utf-8", "replace")[:200]
                except Exception:                                   # noqa: BLE001
                    pass
                hata = EmbeddingUnavailable(f"gomme API {e.code}: {govde_metni}")
                gecici = e.code in RETRYABLE_STATUS
            except Exception as e:                                  # noqa: BLE001
                raise EmbeddingUnavailable(f"gomme API: {type(e).__name__}: {e}") from e
            else:
                # GECIT 2xx GOVDESINDE HATA DONDUREBILIR (Kilo/OpenRouter, yuk
                # altinda HTTP 200 + `{"error":{"code":503,...}}`). Kod durumuna
                # bakmak bunu basari sayardi; `data` yok diye cikan "beklenmeyen
                # yanit" mesaji gercek nedeni (saglayici overload) GIZLERDI.
                h = provider_error_from_body(veri)
                if h is None:
                    break
                mesaj, durum = h
                hata = EmbeddingUnavailable(f"gomme API {mesaj}")
                # Kodsuz (bilinmeyen) govde hatasi gecici sayilir; kalici kod
                # ILK denemede saglayicinin kendi mesajiyla biter.
                gecici = durum is None or durum in RETRYABLE_STATUS
            if not gecici or deneme >= CALL_ATTEMPTS:
                raise hata
            time.sleep(backoff_delay(deneme))
        try:
            sirali = sorted(veri["data"], key=lambda d: d.get("index", 0))
            return [d["embedding"] for d in sirali]
        except (KeyError, TypeError) as e:
            raise EmbeddingUnavailable(
                f"gomme API beklenmeyen yanit: {str(veri)[:160]}") from e

    def _embed(self, texts: list[str], input_type: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        parcalar = []
        for i in range(0, len(texts), self.batch_size):
            parcalar.extend(self._call(texts[i:i + self.batch_size], input_type))
        m = np.asarray(parcalar, dtype=np.float32)
        # L2-normalize: yerel yol da normalize ediyor, indeks kosinus varsayiyor.
        normlar = np.linalg.norm(m, axis=1, keepdims=True)
        normlar[normlar == 0] = 1.0
        return m / normlar

    # -- BGEM3Embedder ile AYNI arayüz ----------------------------------
    def embed(self, texts: list[str], batch_size: int = 12) -> np.ndarray:
        return self._embed(list(texts), "passage")

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text], "query")

    def embed_sparse(self, texts: list[str], batch_size: int = 12) -> list[dict]:
        """API sparse üretmez. Boş ağırlık = sparse sinyali devre dışı."""
        return [{} for _ in texts]

    def embed_chunks(self, chunks, batch_size: int = 12):
        return ([c.chunk_id for c in chunks],
                self._embed([c.text for c in chunks], "passage"))

    def embed_both(self, texts: list[str], batch_size: int = 12):
        return self._embed(list(texts), "passage"), [{} for _ in texts]


class EmbeddingDimensionMismatch(EmbeddingUnavailable):
    """Gömme boyutu indeksin boyutuyla uyuşmuyor — karışık indeks reddedilir.

    NEDEN AYRI TİP: bu bir ağ/sağlayıcı arızası DEĞİL, yapılandırma hatasıdır.
    Yeniden denemek onu düzeltmez; operatör mesajda İKİ boyutu da ve modeli
    görmeden çözemez. Bu yüzden mesaj üçünü ADIYLA söyler.
    """


class _BoyutKapisi:
    """Boyut DEĞİŞMEZİ — uzak gömme sağlayıcıları için ortak kapı.

    Boyut karışımı sessiz bir felakettir: 384'lük yeni vektörler 1024'lük
    indekse yazılamaz (ya da tersi), yazılsa bile kosinüs skorları anlamsızlaşır
    ve ürün yanlış atıf üretir. Kapı İLK gömmeyi (indeks kurulumu) durdurur —
    hiçbir sorgu bundan sonra koşmaz.

    Ölçüm TEK KAYNAK: `MODEL_DIMS` tablosu yalnız uyuşmazlığı ağa çıkmadan ve
    model ADIYLA söyleyebilmek için; tanınmayan modelde bile ölçülen boyut
    indeksin boyutuyla karşılaştırılır.
    """

    #: model adı → YAYINLANMIŞ/ÖLÇÜLMÜŞ boyut (tanınmayan model: yok).
    MODEL_DIMS: dict = {}

    def __init__(self, *, expected_dim: int | None = None, **kw):
        super().__init__(**kw)
        #: İndeksin boyutu. `None` verilirse DEĞİŞMEZ yürürlükte kalır
        #: (`INDEX_DIM`); testler ölçüyü küçültmek için açıkça geçer.
        self.expected_dim = INDEX_DIM if expected_dim is None else int(expected_dim)

    def boyut_dogrula(self, olculen: int) -> None:
        beyan = self.MODEL_DIMS.get(self.model_name)
        if beyan is not None and beyan != olculen:
            raise EmbeddingDimensionMismatch(
                f"{type(self).__name__} modeli {self.model_name!r} {beyan} "
                f"boyutlu olmali, gelen vektor {olculen} boyutlu; uclar "
                "karismis olabilir")
        if olculen != self.expected_dim:
            raise EmbeddingDimensionMismatch(
                f"gomme boyutu indeks boyutuyla uyusmuyor: "
                f"model={self.model_name!r} vektor={olculen} "
                f"indeks={self.expected_dim}. Ayni indekse farkli boyutlu "
                "vektor karistirmak aramayi sessizce bozar: ya modeli indeksin "
                "boyutuna dondur ya indeksi yeniden kur (vektor boyutunu "
                "degistirmek korpusun TAMAMEN yeniden indekslenmesini gerektirir).")

    def _embed(self, texts: list[str], input_type: str) -> np.ndarray:
        if not texts:
            # Boş girdi AĞA ÇIKMAZ (davranış ApiEmbedder ile aynı).
            return np.zeros((0, self.expected_dim), dtype=np.float32)
        m = super()._embed(texts, input_type)
        self.boyut_dogrula(int(m.shape[1]))
        return m


class VoyageEmbedder(_BoyutKapisi, ApiEmbedder):
    """Voyage (`POST {base}/embeddings`, OpenAI biçimi) istemcisi.

    Taşıma OpenAI yoluyla BİREBİR aynıdır (`data[].embedding`); tek gerçek
    fark `input_type` SÖZLÜĞÜ — Voyage `passage`ı reddediyor. Ölçüldü
    2026-09-17:

        400 Value 'passage' supplied for argument 'input_type' is not valid
            -- accepted values are 'query' or 'document'

    Yani rag'in `passage` niyeti Voyage'a `document` olarak gitmeli; aksi hâlde
    HER indeks kurulumu 400 ile düşer. Boyut kapısı ortak (`_BoyutKapisi`).
    """

    INPUT_TYPES = VOYAGE_INPUT_TYPES
    MODEL_DIMS = VOYAGE_MODEL_DIMS


class CohereEmbedder(_BoyutKapisi, ApiEmbedder):
    """Cohere v3 NATIVE (`POST {base}/embed`) istemcisi.

    NEDEN OpenAI-UYUMLU KATMAN DEĞİL (ölçüldü 2026-09-17): Cohere'in uyumluluk
    ucu `input_type` alanını reddediyor (`422 search_query input type is not
    supported for this model`); alanı düşürünce 200 dönüyor ama v3 modellerinin
    retrieval için ihtiyaç duyduğu SORU/PASAJ ayrımı sessizce kayboluyor.
    Native uç alanı kabul ediyor:

        {"model","texts","input_type","embedding_types":["float"]}
        → vektörler `embeddings.float` altında ve GİRİŞ SIRASIYLA

    Toplu boy / zaman aşımı / yeniden deneme / 2xx-gövdesinde-hata davranışı
    `ApiEmbedder`dan MİRAS alınır; yalnız istek gövdesi, uç yolu ve yanıt
    çözümlemesi değişir. `sparse_supported = False` (API'de sparse yok).
    """

    INPUT_TYPES = COHERE_INPUT_TYPES
    MODEL_DIMS = COHERE_MODEL_DIMS

    def _call(self, texts: list[str], input_type: str) -> list:
        govde = {"model": self.model_name, "texts": list(texts),
                 "input_type": self._input_type(input_type),
                 "embedding_types": ["float"]}
        istek = urllib.request.Request(
            f"{self.base_url}/embed", data=json.dumps(govde).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self._key}"} if self._key else {})})
        deneme = 0
        while True:
            deneme += 1
            try:
                with urllib.request.urlopen(istek, timeout=self.timeout) as yanit:
                    veri = json.loads(yanit.read())
            except urllib.error.HTTPError as e:
                govde_metni = ""
                try:
                    govde_metni = e.read().decode("utf-8", "replace")[:200]
                except Exception:                                   # noqa: BLE001
                    pass
                hata = EmbeddingUnavailable(f"cohere gomme API {e.code}: {govde_metni}")
                gecici = e.code in RETRYABLE_STATUS
            except Exception as e:                                  # noqa: BLE001
                raise EmbeddingUnavailable(
                    f"cohere gomme API: {type(e).__name__}: {e}") from e
            else:
                # AYNI SINIF: 2xx gövdesi hata taşıyabilir (bkz. ApiEmbedder notu).
                h = provider_error_from_body(veri)
                if h is None:
                    break
                mesaj, durum = h
                hata = EmbeddingUnavailable(f"cohere gomme API {mesaj}")
                gecici = durum is None or durum in RETRYABLE_STATUS
            if not gecici or deneme >= CALL_ATTEMPTS:
                raise hata
            time.sleep(backoff_delay(deneme))
        return self._vektorler(veri)

    @staticmethod
    def _vektorler(veri) -> list:
        """`embeddings.float` — Cohere native biçimi. Bozuksa ADIYLA hata."""
        try:
            vektorler = veri["embeddings"]["float"]
            if not isinstance(vektorler, list) or not vektorler:
                raise TypeError("embeddings.float bos/dizi degil")
        except (KeyError, TypeError) as e:
            raise EmbeddingUnavailable(
                f"cohere gomme beklenmeyen yanit (embeddings.float yok): "
                f"{str(veri)[:160]}") from e
        return vektorler


def build_embedder(*, provider: str | None = None, **kw):
    """Env'e göre gömme sağlayıcısı kurar.

    `local` (varsayılan) yerel BGE-M3'ü döndürür — ölçülmüş bütün kalite
    sayıları bu yola aittir. `api` OpenAI-uyumlu uca, `cohere` Cohere'in native
    `/v2/embed` ucuna bağlanır; yukarıdaki üç bedel ikisi için de geçerlidir.
    """
    secim = (provider if provider is not None else PROVIDER).strip().lower()
    if secim in ("local", "", "bge", "bgem3"):
        from .embedder import BGEM3Embedder
        e = BGEM3Embedder(**kw)
        # Yerel model sparse ÜRETİR; hibrit retrieval üçüncü ayağını korur.
        e.sparse_supported = True
        return e
    if secim == "api":
        return ApiEmbedder(**kw)
    if secim == "cohere":
        return CohereEmbedder(**kw)
    if secim == "voyage":
        return VoyageEmbedder(**kw)
    raise ValueError(f"bilinmeyen RAG_EMBED_PROVIDER: {secim!r} "
                     "(gecerli: local | api | cohere | voyage)")


def provider_warnings(embedder) -> list:
    """Sağlayıcı seçiminin ölçülmüş bedelleri — açılışta söylenir.

    Sessiz kalite kaybı, gürültülü bir uyarıdan çok daha pahalıdır.
    """
    u = []
    if not getattr(embedder, "sparse_supported", True):
        u.append("Gomme sağlayıcısı SPARSE üretmiyor → hibrit retrieval'ın üç "
                 "ayağından biri (öğrenilmiş lexical) devre dışı; BM25 kalıyor. "
                 "Golden set ölçümleri BGE-M3 ile alındı, bu yapılandırma için "
                 "YENİDEN ÖLÇÜLMELİ.")
    return u
