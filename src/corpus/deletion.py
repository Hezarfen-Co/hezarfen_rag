"""Kaynak silme — KASKAD (#76).

NEDEN VAR (EXP-010/OPS-01 + EVAL-16): indekslerin genel API'si yalnız
`build/search` idi; `delete` **yoktu** ve `build()` her çağrıda koleksiyonu
silip sıfırdan kuruyordu. Daha temeli: chunk→kaynak eşlemesi (`doc_id`)
hiçbir indekste payload olarak tutulmuyordu → *"şu kaynağın vektörlerini sil"*
sorgusu **teknik olarak ifade edilemiyordu**.

BAŞARISIZLIK SENARYOSU: öğretmen ders notunu siler → vektör silinemez →
**silinmiş nottan alıntı yapan cevaplar üretilmeye devam eder**. `ResponseCache`
TTL boyunca eski cevap döner. RES-003'ün *"kaynak silinince chunk + vector +
cache + özet + trace hepsi silinir"* gerekliliği karşılanmıyordu ve **KVKK
silme yükümlülüğü imkânsızdı**.

TASARIM KARARLARI

1. **Kaskad tek yerde.** Silmeyi üç indekse ayrı ayrı çağırmak, birinin
   unutulmasına açık kapı bırakır. Buradaki tek fonksiyon hepsini sırayla
   siler ve **ne sildiğini rapor eder**.
2. **Cache anahtar-uzayı geçersizleştirilir.** Vektör silinse bile
   `ResponseCache` eski cevabı TTL boyunca döndürür. Tek doğru yol
   `corpus_version`'ı değiştirmektir (#77 ile birlikte çalışır) — tek tek
   anahtar silmek imkânsız, çünkü hangi soruların o kaynağa dayandığı
   bilinmiyor.
3. **Silme olayı kalıcı ize yazılır.** KVKK'da "sildim" demek yetmez, ne zaman
   ve neyin silindiği gösterilebilmelidir.
4. **Kısmi başarısızlık gizlenmez.** Bir indeks silemezse sonuç `tam=False`
   döner; çağıran yeniden dener ya da operatöre bildirir. Sessiz başarı,
   silinmemiş veriyi silinmiş sanmak demektir — en tehlikeli durum.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict

# Silme olaylarının kalıcı izi. Kapalıysa (yol yok) silme yine çalışır ama
# kanıtlanamaz — üretimde doldurulmalıdır.
DELETION_LOG = os.environ.get("HEZARFEN_DELETION_LOG") or ""


@dataclass
class DeletionResult:
    doc_id: str
    dense: int = 0
    bm25: int = 0
    sparse: int = 0
    cache_invalidated: bool = False
    new_corpus_version: str = ""
    errors: list = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.dense + self.bm25 + self.sparse

    @property
    def complete(self) -> bool:
        """Hiçbir adım hata vermediyse tam."""
        return not self.errors

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total"] = self.total
        d["complete"] = self.complete
        return d


def _try(sonuc: DeletionResult, ad: str, fn):
    try:
        return fn()
    except Exception as e:                       # noqa: BLE001
        sonuc.errors.append(f"{ad}: {type(e).__name__}: {e}")
        return 0


def delete_source(doc_id: str, *, dense=None, bm25=None, sparse=None,
                  response_cache=None, corpus_version: str = "",
                  log_path: str | None = None) -> DeletionResult:
    """Bir kaynağı BÜTÜN katmanlardan siler.

    `corpus_version` verilirse yeni bir sürüm üretilir ve döndürülür; çağıran
    bunu `Generator(corpus_version=...)`'a vermelidir. Cache anahtarı sürümü
    içerdiği için (#77) bu, o kaynağa dayanan tüm eski cevapları tek hamlede
    geçersiz kılar.
    """
    sonuc = DeletionResult(doc_id=doc_id)
    if not doc_id:
        sonuc.errors.append("doc_id bos")
        return sonuc

    if dense is not None:
        sonuc.dense = _try(sonuc, "dense", lambda: dense.delete(doc_id))
    if bm25 is not None:
        sonuc.bm25 = _try(sonuc, "bm25", lambda: bm25.delete(doc_id))
    if sparse is not None:
        sonuc.sparse = _try(sonuc, "sparse", lambda: sparse.delete(doc_id))

    # Cache: tek tek anahtar silinemez (hangi soruların bu kaynağa dayandığı
    # bilinmiyor) — anahtar uzayını sürüm değiştirerek geçersiz kılıyoruz.
    if response_cache is not None or corpus_version:
        sonuc.new_corpus_version = bump_version(corpus_version)
        sonuc.cache_invalidated = True

    _log(sonuc, log_path)
    return sonuc


def bump_version(corpus_version: str) -> str:
    """`v3` → `v4`, `abc123` → `abc123+1`. Boşsa zaman damgalı bir sürüm.

    Amaç monoton ve GÖRÜNÜR olması: logda "sürüm değişti" görülebilmeli.
    """
    if not corpus_version:
        return f"v{int(time.time())}"
    if corpus_version.startswith("v") and corpus_version[1:].isdigit():
        return f"v{int(corpus_version[1:]) + 1}"
    if "+" in corpus_version:
        taban, _, n = corpus_version.rpartition("+")
        if n.isdigit():
            return f"{taban}+{int(n) + 1}"
    return f"{corpus_version}+1"


def _log(sonuc: DeletionResult, log_path: str | None = None) -> bool:
    """Silme olayını kalıcı ize yazar. KVKK: "sildim" demek yetmez."""
    yol = log_path if log_path is not None else DELETION_LOG
    if not yol:
        return False
    kayit = sonuc.to_dict()
    kayit["ts"] = time.time()
    kayit["utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(kayit["ts"]))
    try:
        os.makedirs(os.path.dirname(yol) or ".", exist_ok=True)
        with open(yol, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(kayit, ensure_ascii=False) + "\n")
        return True
    except Exception:                            # noqa: BLE001
        # Telemetri hatası silmeyi geçersiz kılmaz; ama sessiz de kalmaz.
        sonuc.errors.append("silme izi yazilamadi")
        return False


def read_log(log_path: str | None = None) -> list[dict]:
    """Silme izini okur (denetim/kanıt için)."""
    yol = log_path if log_path is not None else DELETION_LOG
    if not yol or not os.path.isfile(yol):
        return []
    out = []
    with open(yol, encoding="utf-8") as fh:
        for satir in fh:
            satir = satir.strip()
            if satir:
                try:
                    out.append(json.loads(satir))
                except json.JSONDecodeError:
                    continue
    return out
