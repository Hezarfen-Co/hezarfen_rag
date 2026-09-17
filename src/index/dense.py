"""Faz 1.3 — Qdrant yerel (gömülü) dense vektör indeksi + exact referans.

BGE-M3 dense (1024-dim, L2-normalize) → cosine mesafe. Gömülü mod (sunucu yok):
`path=None` → in-memory (test); `path=...` → kalıcı yerel depo. Üretimde Qdrant
sunucu konteyneri aynı arayüzle takılır.

Kabul (plan 1.3): ANN recall ≥ 0.995 (exact brute-force'a karşı). NOT: Qdrant'ın
gömülü yerel modu küçük koleksiyonda exact hesaplar (recall=1.0); gerçek HNSW/ANN
kaybı ölçekte (sunucu) yeniden ölçülecek. `exact_topk` referans olarak burada.
"""
from __future__ import annotations

import numpy as np

_COLLECTION = "chunks"


def exact_topk(query_vec, matrix, ids, top_k: int = 20):
    """Brute-force cosine (referans doğruluk). matrix satırları normalize varsayılmaz."""
    from src.embed import cosine_matrix
    scores = cosine_matrix(query_vec, matrix)
    order = np.argsort(-scores)[:top_k]
    return [(ids[i], float(scores[i])) for i in order]


class DenseIndex:
    """Qdrant gömülü dense indeks. build(ids, vectors) → search(query_vec, k)."""

    def __init__(self, dim: int = 1024, path: str | None = None,
                 collection: str = _COLLECTION):
        self.dim = dim
        self.collection = collection
        self._path = path
        self._client = None
        self._ids: list[str] = []

    def _c(self):
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = (QdrantClient(path=self._path) if self._path
                            else QdrantClient(":memory:"))
        return self._client

    def build(self, ids, vectors, payloads=None, *, school,
              doc_id: str = "", source_version: str = ""):
        """Koleksiyonu SIFIRDAN kurar (var olanı siler).

        `doc_id`/`source_version` her noktanın payload'ına yazılır — `delete()`
        ve `upsert()` bunlar olmadan çalışamaz (bkz. `delete` docstring'i).

        `school` ZORUNLUDUR ve varsayılanı YOKTUR (bkz. `guard/tenant.py`):
        sahipsiz yazma bir hata, "paylaşılan/public bir satır" değil. Her
        korpusun bir okulu vardır; okulsuz satır yazılamaz ve okunamaz.
        """
        from qdrant_client.models import Distance, VectorParams
        c = self._c()
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[1] != self.dim:
            raise ValueError(f"vectors (n,{self.dim}) olmalı, geldi {vectors.shape}")
        if c.collection_exists(self.collection):
            c.delete_collection(self.collection)
        c.create_collection(
            self.collection,
            vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
        )
        self._ids = []
        self._next_id = 0
        self.upsert(ids, vectors, payloads, school=school, doc_id=doc_id,
                    source_version=source_version)
        return self

    # M4-2 (#76, EXP-010/OPS-01) — SILME/GUNCELLEME API'SI YOKTU.
    #
    # OLCULDU: genel API yalniz `build/search/collection/dim` idi; `build()`
    # her cagrida koleksiyonu SILIP SIFIRDAN kuruyordu (10 nokta build ->
    # 5 yeni id ile build -> koleksiyonda 5 nokta kaldi, 15 degil).
    #
    # Daha temeli: chunk -> KAYNAK eslemesi hicbir indekste payload olarak
    # tutulmuyordu (`payload={"chunk_id": cid}`) -> "su kaynagin vektorlerini
    # sil" sorgusu TEKNIK OLARAK IFADE EDILEMIYORDU.
    #
    # BASARISIZLIK: ogretmen ders notunu silerse vektor silinemez -> silinmis
    # nottan alinti yapan cevaplar uretilmeye DEVAM EDER. KVKK silme
    # yukumlulugu de imkansiz hale gelir.

    def upsert(self, ids, vectors, payloads=None, *, school,
               doc_id: str = "", source_version: str = ""):
        """Var olan koleksiyona EKLER/GUNCELLER — silmez.

        Ayni `chunk_id` yeniden gelirse eski nokta silinip yenisi yazilir
        (id'ler sirali tamsayi oldugu icin dogal bir upsert anahtari yok;
        chunk_id filtresiyle silip ekliyoruz).

        `school` (ZORUNLU) her noktanin payload'ina yazilir: koleksiyon
        korpus-omru boyunca de-okunur (kalici/sunucu Qdrant'ta paylasilir) ve
        okuma tarafi ancak bu damgayla kapsamlanabilir."""
        from qdrant_client.models import PointStruct
        from ..guard.tenant import require_owner
        sahip = require_owner(school)
        c = self._c()
        vectors = np.asarray(vectors, dtype=np.float32)
        if len(vectors) == 0:
            return self
        if vectors.ndim != 2 or vectors.shape[1] != self.dim:
            raise ValueError(f"vectors (n,{self.dim}) olmalı, geldi {vectors.shape}")
        if not hasattr(self, "_next_id"):
            self._next_id = len(self._ids)
        yeniden = [cid for cid in ids if cid in set(self._ids)]
        if yeniden:
            self.delete_chunks(yeniden)
        pts = []
        for i, (cid, v) in enumerate(zip(ids, vectors)):
            pl = {"chunk_id": cid, "school": sahip}
            if doc_id:
                pl["doc_id"] = doc_id
            if source_version:
                pl["source_version"] = source_version
            if payloads:
                pl.update(payloads[i])
            pts.append(PointStruct(id=self._next_id, vector=v.tolist(), payload=pl))
            self._next_id += 1
        c.upsert(self.collection, points=pts)
        self._ids.extend(ids)
        return self

    def delete(self, doc_id: str) -> int:
        """Bir KAYNAGIN tum vektorlerini siler. Doner: silinen nokta sayisi.

        `doc_id` payload'da tutulmadan bu sorgu ifade edilemez — bu yuzden
        `build`/`upsert` onu yaziyor. Eski (doc_id'siz) koleksiyonlarda hicbir
        sey silinmez ve 0 doner; cagiran bunu bir HATA olarak gormeli.
        """
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        c = self._c()
        if not c.collection_exists(self.collection):
            return 0
        flt = Filter(must=[FieldCondition(key="doc_id",
                                          match=MatchValue(value=doc_id))])
        kalan_once = len(self)
        silinecek = {p.payload.get("chunk_id")
                     for p in self._scroll(flt)}
        c.delete(self.collection, points_selector=flt)
        self._ids = [cid for cid in self._ids if cid not in silinecek]
        return kalan_once - len(self._ids)

    def delete_chunks(self, chunk_ids) -> int:
        """Belirli chunk'lari siler (upsert'in guncelleme yolu)."""
        from qdrant_client.models import FieldCondition, Filter, MatchAny
        c = self._c()
        if not c.collection_exists(self.collection):
            return 0
        hedef = list(chunk_ids)
        if not hedef:
            return 0
        flt = Filter(must=[FieldCondition(key="chunk_id",
                                          match=MatchAny(any=hedef))])
        c.delete(self.collection, points_selector=flt)
        once = len(self._ids)
        kume = set(hedef)
        self._ids = [cid for cid in self._ids if cid not in kume]
        return once - len(self._ids)

    def _scroll(self, flt=None, limit: int = 10_000):
        c = self._c()
        pts, _ = c.scroll(self.collection, scroll_filter=flt, limit=limit,
                          with_payload=True, with_vectors=False)
        return pts

    def doc_ids(self) -> set:
        """Koleksiyondaki kaynaklar — silme denetimi icin."""
        return {p.payload.get("doc_id") for p in self._scroll()
                if p.payload.get("doc_id")}

    def search(self, query_vec, top_k: int = 20, *, school=None):
        """(chunk_id, skor) listesi, skor azalan. Skor = cosine (dense normalize).

        `school` = OKURUN okulu (istekten). Kapsam TAM EŞİTLİKTİR: yalnız o
        okulun satırları döner; başka bir okulunki de damgasız (eski) satır da
        dönmez. Okulsuz okur (`school=None`) HİÇBİR satır görmez — okul yokluğu
        "hepsi" demek değildir (bkz. guard/tenant.py).

        Kapsam SÜZGEÇLE ifade edilir, `limit` sonrası kırpmayla DEĞİL: aksi
        hâlde yabancı okulun satırları `top_k`yı doldurup kendi okulunun
        sonuçlarını dışarıda bırakırdı."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        from ..guard.tenant import visible_owners
        c = self._c()
        q = np.asarray(query_vec, dtype=np.float32).tolist()
        sahipler = sorted(visible_owners(school))
        if not sahipler:                      # okulsuz okur → hiçbir satır yok
            return []
        flt = Filter(must=[FieldCondition(key="school",
                                          match=MatchValue(value=sahipler[0]))])
        res = c.query_points(self.collection, query=q, limit=top_k,
                             query_filter=flt).points
        return [(p.payload["chunk_id"], float(p.score)) for p in res]

    def __len__(self):
        return len(self._ids)
