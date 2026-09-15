"""Gömme (embedding) sağlayıcı seçimi: yerel model ↔ uzak API.

NEDEN: yerel BGE-M3 sorgu anında ucuz (CPU'da 0,122 s) ama **indeks kurulumu**
CPU'da 548 s sürüyor (GPU'da 47,6 s) ve indeks bellekte olduğu için bu bedel
her yeniden başlatmada ödeniyor (#75). Uzak API bu iki maliyeti de ortadan
kaldırır; karşılığında ağa bağımlılık ve sorgu başına ücret getirir.

SEÇİM `RAG_EMBED_PROVIDER` ile yapılır: `local` (varsayılan) | `api`.

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
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import numpy as np

PROVIDER = os.environ.get("RAG_EMBED_PROVIDER", "local").strip().lower()
API_BASE = os.environ.get("RAG_EMBED_API_BASE", "").rstrip("/")
API_MODEL = os.environ.get("RAG_EMBED_MODEL", "")
API_KEY_ENV = os.environ.get("RAG_EMBED_API_KEY_ENV", "RAG_EMBED_API_KEY")
API_TIMEOUT = float(os.environ.get("RAG_EMBED_TIMEOUT_S", "30"))
API_BATCH = int(os.environ.get("RAG_EMBED_BATCH", "32"))


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

    def _call(self, texts: list[str], input_type: str) -> list:
        govde = {"model": self.model_name, "input": list(texts),
                 "encoding_format": "float"}
        # NVIDIA NIM ve Cohere `input_type` ister (query/passage ayrimi retrieval
        # kalitesini belirgin degistirir); OpenAI yok sayar. Gondermek guvenli.
        govde["input_type"] = input_type
        istek = urllib.request.Request(
            f"{self.base_url}/embeddings", data=json.dumps(govde).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self._key}"} if self._key else {})})
        try:
            with urllib.request.urlopen(istek, timeout=self.timeout) as yanit:
                veri = json.loads(yanit.read())
        except urllib.error.HTTPError as e:
            govde_metni = ""
            try:
                govde_metni = e.read().decode("utf-8", "replace")[:200]
            except Exception:                                   # noqa: BLE001
                pass
            raise EmbeddingUnavailable(
                f"gomme API {e.code}: {govde_metni}") from e
        except Exception as e:                                  # noqa: BLE001
            raise EmbeddingUnavailable(f"gomme API: {type(e).__name__}: {e}") from e
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


def build_embedder(*, provider: str | None = None, **kw):
    """Env'e göre gömme sağlayıcısı kurar.

    `local` (varsayılan) yerel BGE-M3'ü döndürür — ölçülmüş bütün kalite
    sayıları bu yola aittir. `api` uzak uca bağlanır; yukarıdaki üç bedel
    geçerlidir.
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
    raise ValueError(f"bilinmeyen RAG_EMBED_PROVIDER: {secim!r} "
                     "(gecerli: local | api)")


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
