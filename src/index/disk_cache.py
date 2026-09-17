"""İNDEKS ÖNBELLEĞİ — vektörler diskte, konteyner yeniden yaratılsa da kalır (#75).

NEDEN: indeks bellekte tutulduğu için her yeniden başlatmada chunk'lar YENİDEN
GÖMÜLÜR (ağ çağrısı + gecikme; yerel yolda CPU'da ~548 s). Korpus (PDF) host
bind mount'unda KALICI, ama ondan TÜREYEN indeks kayboluyordu — yani yeniden
yaratılan konteyner soruları bir süre "kaynak yok / hazırlanıyor" diye
yanıtlıyordu. Bu modül gömme ÇIKTISINI (`ids`, `vecs`, `sparse`) bir volume'e
yazar; aynı içerik + aynı model için bir sonraki kurulum ağı ATLAR.

ANAHTAR İÇERİK TÜREVLİDİR (yanlış isabet imkansız):
  * `doc_id` = PDF sha256'nın ilk 12'si (içerik değişirse değişir);
  * `text_digest` = gömülen chunk metinlerinin sha256'sı (chunker değişirse);
  * `embed_sig` = sağlayıcı + taban + model + boyut (model değişirse).
Üçünden biri değişirse anahtar değişir → önbellek ıskalar → yeniden gömülür.
OKUL anahtara GİRMEZ: gömme saf içerik türevlidir, iki okulun aynı baytlı
kitabı aynı vektörleri paylaşır (meta/atıf okul damgası çağrı yerinde kurulur).

BİÇİM: `.npz` (`allow_pickle=False`) — JSON gövdesi bayt dizisi olarak saklanır;
`pickle` YOK (yüklenen dosya servisin kendi yazdığı olsa da keyfi kod çalıştırma
yüzeyi açmamak için). Bozuk/eksik dosya bir HATA değil, ıska sayılır.

KAPALI VARSAYILAN: `RAG_INDEX_CACHE` boşsa önbellek devre dışıdır (mevcut
davranış korunur; testler ve eval hermetik kalır). Dağıtımda `Containerfile`
`/index`e, compose `rag-index` volume'üne bağlar.
"""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np

ENV = "RAG_INDEX_CACHE"
_FORMAT = 1


def cache_root(env: dict | None = None) -> str:
    """Önbellek dizini (`RAG_INDEX_CACHE`); boş/ayarsız → devre dışı ("")."""
    kaynak = env if env is not None else os.environ
    return (kaynak.get(ENV) or "").strip()


def embed_signature(provider: str, api_base: str, api_model: str,
                    dim: int) -> str:
    """Gömme uzayının kimliği — farklı model = farklı anahtar (bkz. provider.py)."""
    return f"{provider}|{api_base}|{api_model}|{dim}"


def cache_key(doc_id: str, texts, embed_sig: str) -> str:
    """İçerik türevli anahtar (bkz. modül başlığı)."""
    h = hashlib.sha256()
    h.update(f"v{_FORMAT}|{doc_id}|{embed_sig}|".encode())
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:20]


def _path(root: str, doc_id: str, key: str) -> str:
    return os.path.join(root, f"{doc_id}.{key}.npz")


def save(root: str, doc_id: str, key: str, ids, vecs, sparse) -> str | None:
    """Vektörleri atomik yazar (tmp + replace). Hata SIZMAZ: önbellek yazımı
    kurulumu düşürmemeli (diskte yer yoksa indeks yine kurulmuş olur)."""
    if not root:
        return None
    try:
        os.makedirs(root, exist_ok=True)
        hedef = _path(root, doc_id, key)
        gecici = hedef + ".tmp"
        with open(gecici, "wb") as fh:
            np.savez(
                fh,
                ids=np.array([str(i) for i in ids]),
                vecs=np.asarray(vecs, dtype=np.float32),
                sparse_json=np.frombuffer(
                    json.dumps(sparse).encode("utf-8"), dtype=np.uint8),
            )
        os.replace(gecici, hedef)
        return hedef
    except Exception:                                  # noqa: BLE001
        return None


def load(root: str, doc_id: str, key: str, *, dim: int, n: int):
    """(ids, vecs, sparse) döner; dosya yok/bozuk/uyuşmuyorsa None (ıska)."""
    if not root:
        return None
    try:
        with np.load(_path(root, doc_id, key), allow_pickle=False) as z:
            ids = [str(x) for x in z["ids"].tolist()]
            vecs = z["vecs"]
            sparse = json.loads(bytes(z["sparse_json"].tobytes()).decode("utf-8"))
    except Exception:                                  # noqa: BLE001
        return None
    if len(ids) != n or vecs.shape != (n, dim) or len(sparse) != n:
        return None
    return ids, vecs, sparse
