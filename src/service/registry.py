"""Çok-korpus yönlendirme (#86, EXP-010/OPS-08+09+18).

ÖLÇÜLEN DURUM: süreç = **1 kitap = 1 ders**. `build_service(book_path, sinif=,
ders=)`, tek `BOOK_PATH` env, tek `doc`, tek indeks üçlüsü, tek `Generator`.
Kaynak kataloğu, yönlendirme, indeks kataloğu **yoktu**.

ÜRÜN AÇISINDAN NE DEMEK: öğrencinin 19 dersi var; servis yalnız birini
cevaplayabiliyor. Bir okul demosunda öğrenci fiziğe geçtiği anda ürün
"kaynaklarda bulunamadı" diyor — bu bir RAG hatası gibi görünüyor ama aslında
**yanlış korpusa soruluyor**.

BU MODÜL NE YAPAR: birden çok (sınıf, ders) korpusunu tutar ve isteği
**rolün/kapsamın** gösterdiği korpusa yönlendirir. Yetki kararı yine
`guard/roles.can_access` ile verilir — yönlendirme bir yetkilendirme DEĞİLDİR
ve onun yerine geçmez.

BU MODÜL NE YAPMAZ (dürüst sınır): ölçek duvarını kaldırmaz. Ölçüldü
(bu makine, CPU):

| | 10k chunk | 50k chunk | 100k chunk |
|---|---|---|---|
| dense arama (top-40) | 176 ms | 234 ms | — |
| dense RSS artışı | +529 MB | **+2.139 MB** | — |
| BM25 arama | 12,3 ms | 59,4 ms | **131,5 ms** |
| sparse arama (saf Python) | 80,8 ms | **419,1 ms** | — |

50 okul × 10 ders ≈ 129k chunk → RSS ~5,7 GB, tek sorgu ~1,8 s ve GIL altında
**seri**. Bu ancak **kalıcı vektör store** ile çözülür (#75). Buradaki kayıt
defteri, o gelene kadar birkaç korpusu (bir okulun dersleri) tek süreçte
servis etmeyi mümkün kılar ve sınırı **görünür** tutar.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from .handler import scope_pairs


@dataclass(frozen=True)
class CorpusKey:
    sinif: str
    ders: str

    def __str__(self) -> str:
        return f"{self.sinif}/{self.ders}"


@dataclass
class RegistryStats:
    corpora: int = 0
    chunks: int = 0
    detail: dict = field(default_factory=dict)


class CorpusRegistry:
    """(sınıf, ders) → `RagService` kayıt defteri ve yönlendirici.

    Thread-güvenlidir: kayıt/silme kilit altında, okuma kilitsiz (sözlük
    okuması atomik). Servisin kendisi zaten eşzamanlı isteklere açık.
    """

    def __init__(self, *, max_corpora: int = 0):
        """`max_corpora`: 0 = sınırsız. Sınır **bilinçli** bir güvenlik valfi:
        ölçek duvarı ölçüldü (#75 çözülene kadar RSS lineer büyüyor), sessizce
        belleği tüketmektense açıkça reddetmek yeğdir."""
        self._services: dict[CorpusKey, object] = {}
        self._lock = threading.Lock()
        self.max_corpora = int(max_corpora or 0)

    # -- kayıt -----------------------------------------------------------
    def register(self, service, *, sinif: str | None = None,
                 ders: str | None = None):
        """Bir korpusu deftere ekler. Sınıf/ders verilmezse servisten okunur."""
        s = sinif if sinif is not None else getattr(
            getattr(service, "doc", None), "sinif", None)
        d = ders if ders is not None else (
            getattr(service, "ders", None)
            or getattr(getattr(service, "doc", None), "ders", None))
        if not s or not d:
            raise ValueError("korpus sinif/ders bilgisi olmadan kaydedilemez")
        anahtar = CorpusKey(str(s), str(d))
        with self._lock:
            if (self.max_corpora and anahtar not in self._services
                    and len(self._services) >= self.max_corpora):
                raise ValueError(
                    f"korpus siniri asildi ({self.max_corpora}) — "
                    "kalici vektor store olmadan bellek lineer buyur (#75)")
            self._services[anahtar] = service
        return anahtar

    def unregister(self, sinif: str, ders: str) -> bool:
        with self._lock:
            return self._services.pop(CorpusKey(str(sinif), str(ders)),
                                      None) is not None

    # -- yönlendirme -----------------------------------------------------
    def get(self, sinif: str | None, ders: str | None):
        if not sinif or not ders:
            return None
        return self._services.get(CorpusKey(str(sinif), str(ders)))

    def resolve(self, req: dict):
        """İsteği bir korpusa yönlendirir. Döner: `(service, reason)`.

        `service` None ise `reason` neden bulunamadığını söyler:
          `no_corpus`        — o sınıf/ders için korpus yüklü değil
          `corpus_ambiguous` — hedef belirlenemedi (rol tek ders taşımıyor)

        **YÖNLENDİRME YETKİLENDİRME DEĞİLDİR.** Burada yalnız "hangi kitap"
        sorusu cevaplanır; "bu öğrenci o kitabı görebilir mi" sorusunu
        `guard/roles.can_access` cevaplar ve servis onu ayrıca uygular. İkisini
        karıştırmak, rolün istediği dersi seçmesine izin vermek demek olurdu —
        SEC-01'in tam olarak bu şekli ölçülmüştü.
        """
        rol = req.get("role") or {}
        raw_scope = req.get("scope")
        # YENİ rag.chat biçimi: `scope` bir (sınıf,ders) ÇİFT listesidir. Eski
        # sözlük biçimi (`{"sinif","ders"}`) aynen çalışmaya devam eder.
        pairs = scope_pairs(raw_scope) if isinstance(raw_scope, (list, tuple)) else []
        if pairs:
            if len(pairs) == 1:
                sinif, ders = pairs[0]
            else:
                yuklu = [(s, d) for (s, d) in pairs if self.get(s, d) is not None]
                if len(yuklu) == 1:
                    sinif, ders = yuklu[0]
                else:
                    # Birden çok aday: hedef belirsiz. Tahmin yanlış kitap demek.
                    return None, "corpus_ambiguous"
            svc = self.get(sinif, ders)
            return (svc, "") if svc is not None else (None, "no_corpus")
        scope = raw_scope if isinstance(raw_scope, dict) else {}
        sinif = scope.get("sinif") or rol.get("sinif")
        ders = scope.get("ders") or (req.get("options") or {}).get("ders")

        if not ders:
            dersler = list(rol.get("ders_list") or [])
            if len(dersler) == 1:
                ders = dersler[0]
            elif len(dersler) > 1:
                # Birden çok ders: hedef belirsiz. Tahmin etmek yanlış kitaptan
                # cevap üretmek demek olurdu.
                mevcut = [d for d in dersler if self.get(sinif, d) is not None]
                if len(mevcut) == 1:
                    ders = mevcut[0]
                else:
                    return None, "corpus_ambiguous"

        svc = self.get(sinif, ders)
        return (svc, "") if svc is not None else (None, "no_corpus")

    # -- gözlem ----------------------------------------------------------
    def keys(self) -> list[CorpusKey]:
        return sorted(self._services, key=str)

    def stats(self) -> RegistryStats:
        detay, toplam = {}, 0
        for k, svc in list(self._services.items()):
            n = len(getattr(getattr(svc, "generator", None), "chunks_by_id", {}) or {})
            detay[str(k)] = n
            toplam += n
        return RegistryStats(corpora=len(detay), chunks=toplam, detail=detay)

    def __len__(self) -> int:
        return len(self._services)

    def __contains__(self, item) -> bool:
        if isinstance(item, CorpusKey):
            return item in self._services
        return False
