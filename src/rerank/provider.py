"""Yeniden sıralayıcı (rerank) sağlayıcı seçimi: yerel ↔ uzak API ↔ kapalı.

NEDEN BU KATMAN VAR: rerank, GPU'yu isteyen **tek** parçadır. CPU'da sorgu
başına ölçülen dağılım (EXP-018):

    sorgu embed        0,122 s   önemsiz
    hibrit arama       ms        önemsiz
    rerank (40 aday)  95,9 s     ** bütün sorun burada **
    LLM (LLMClient)    ~2-3 s     zaten uzak servis

Yani rerank uzak bir servise taşınırsa ya da kapatılırsa CPU sorgu tarafında
yeterli olur. Seçim `RAG_RERANK_PROVIDER` ile: `local` (varsayılan) | `api` |
`off`.

=== `off` HAKKINDA DÜRÜST UYARI ===
"Rerank'i kaldıralım" seçeneği ölçümle DESTEKLENMİŞ DEĞİLDİR. EXP-018'de
golden set üzerinde RRF'nin reranker'ı geçtiği görüldü (r@6 0,939 vs 0,890)
AMA bu ölçüm reranker'ın ALEYHİNE kuruludur: 66 item'ın 55'inde sorgu,
birimin KENDİ METNİDİR (iğne testi), soru değil. Cross-encoder soru↔pasaj
ilgisine bakmak üzere eğitilmiştir. Tek soru biçimli kategoride (`global`)
reranker öndeydi. Yani bu set "reranker işe yarıyor mu" sorusunu
**cevaplayamaz**; `off` ucuz olduğu için cazip görünür, ölçülmüş olduğu için
değil (#91: insan yazımı soru gerekiyor).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

PROVIDER = os.environ.get("RAG_RERANK_PROVIDER", "local").strip().lower()
API_URL = os.environ.get("RAG_RERANK_API_URL", "").rstrip("/")
API_MODEL = os.environ.get("RAG_RERANK_MODEL", "")
API_KEY_ENV = os.environ.get("RAG_RERANK_API_KEY_ENV", "RAG_RERANK_API_KEY")
API_TIMEOUT = float(os.environ.get("RAG_RERANK_TIMEOUT_S", "30"))


class RerankUnavailable(RuntimeError):
    """Rerank sağlayıcısına ulaşılamıyor."""


class NoOpReranker:
    """Rerank kapalı: aday sırası (RRF) korunur.

    Skor olarak azalan yapay bir değer verilir çünkü aşağı akıştaki ilgililik
    süzgeci (`rerank_select`) skor bekler. Yapay skorlar 1,0'dan başlayıp eşit
    aralıkla düşer; böylece `relevance_min`/`relevance_rel` süzgeci **hiçbir
    adayı elemez** — kapalı rerank, sessizce bir eleme kapısına dönüşmemeli.

    *** KRİTİK: ÇEKİMSERLİK KAPISI BOZULUR ***
    Ürünün fail-closed kanıt kapısı `contexts[0].score < abstain_score` (0,30)
    kuralıyla çalışır ve bu eşik reranker'ın sigmoid skorlarına göre ölçüldü
    (EXP-017: cevapsız sorular 0,09-0,34, cevaplanabilirler 0,50+). Yapay
    skorlar HER ZAMAN 1,0'dan başladığı için kapı **hiç tetiklenmez**: ürün
    kitapta olmayan soruya da cevap üretmeye çalışır. Okul ortamında bu,
    uydurma riskinin en yüksek olduğu durumdur.

    Bu yüzden `calibrated_scores = False`: çağıran katman kapıyı kapalı
    bırakamaz, açıkça onaylamak zorundadır (bkz. `check_abstain_compatibility`).
    """

    sparse_supported = True          # ilgisiz ama arayüz tutarlılığı için
    calibrated_scores = False        # skorlar kanıt kapısı için ANLAMSIZ

    def rerank(self, query: str, items, top_k: int | None = None,
               normalize: bool = True):
        n = len(items)
        if n == 0:
            return []
        out = [(cid, 1.0 - (i / (n * 2.0))) for i, (cid, _t) in enumerate(items)]
        return out[:top_k] if top_k else out


class ApiReranker:
    """Cohere / Jina uyumlu rerank istemcisi.

    `calibrated_scores = False`: API skorları 0-1 aralığındadır ama BGE'nin
    sigmoid dağılımıyla AYNI DEĞİLDİR. `abstain_score=0,30` eşiği BGE üzerinde
    ölçüldü; başka bir modelin skor dağılımına uygulamak, eşiği ölçmeden
    taşımak olur. Yeni sağlayıcı için EXP-017 kalibrasyonu TEKRAR koşulmalıdır
    (`python -m src.eval.calibrate_abstain_cli`).

    İki yaygın yanıt biçimi desteklenir; ikisi de `results[]` içinde `index` ve
    `relevance_score` döndürür. Biçim tanınmazsa **istisna atılır** — sessizce
    aday sırasına düşmek, kalite kaybını görünmez kılardı.
    """

    calibrated_scores = False

    def __init__(self, *, url: str | None = None, model: str | None = None,
                 api_key: str | None = None, timeout: float | None = None):
        self.url = (url if url is not None else API_URL).rstrip("/")
        self.model_name = model if model is not None else API_MODEL
        self.timeout = API_TIMEOUT if timeout is None else float(timeout)
        self._key = api_key if api_key is not None else os.environ.get(API_KEY_ENV, "")
        if not self.url:
            raise ValueError("API rerank icin RAG_RERANK_API_URL gerekli")

    def rerank(self, query: str, items, top_k: int | None = None,
               normalize: bool = True):
        if not items:
            return []
        idler = [cid for cid, _ in items]
        metinler = [t for _, t in items]
        govde = {"query": query, "documents": metinler}
        if self.model_name:
            govde["model"] = self.model_name
        if top_k:
            govde["top_n"] = int(top_k)
        istek = urllib.request.Request(
            self.url, data=json.dumps(govde).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self._key}"} if self._key else {})})
        try:
            with urllib.request.urlopen(istek, timeout=self.timeout) as yanit:
                veri = json.loads(yanit.read())
        except urllib.error.HTTPError as e:
            metin = ""
            try:
                metin = e.read().decode("utf-8", "replace")[:200]
            except Exception:                                   # noqa: BLE001
                pass
            raise RerankUnavailable(f"rerank API {e.code}: {metin}") from e
        except Exception as e:                                  # noqa: BLE001
            raise RerankUnavailable(f"rerank API: {type(e).__name__}: {e}") from e

        sonuclar = veri.get("results")
        if not isinstance(sonuclar, list):
            raise RerankUnavailable(
                f"rerank API beklenmeyen yanit: {str(veri)[:160]}")
        out = []
        for r in sonuclar:
            i = r.get("index")
            s = r.get("relevance_score", r.get("score"))
            if i is None or s is None or not (0 <= int(i) < len(idler)):
                raise RerankUnavailable(f"rerank API bozuk kayit: {str(r)[:120]}")
            out.append((idler[int(i)], float(s)))
        out.sort(key=lambda x: -x[1])
        return out[:top_k] if top_k else out


def build_reranker(*, provider: str | None = None, **kw):
    """Env'e göre rerank sağlayıcısı kurar."""
    secim = (provider if provider is not None else PROVIDER).strip().lower()
    if secim in ("local", "", "bge"):
        from .reranker import BGEReranker
        return BGEReranker(**kw)
    if secim == "api":
        return ApiReranker(**kw)
    if secim in ("off", "none", "yok"):
        return NoOpReranker()
    raise ValueError(f"bilinmeyen RAG_RERANK_PROVIDER: {secim!r} "
                     "(gecerli: local | api | off)")


ALLOW_UNCALIBRATED = os.environ.get(
    "RAG_ALLOW_UNCALIBRATED_ABSTAIN", "").strip().lower() in (
        "1", "true", "yes", "on")


def check_abstain_compatibility(reranker, *, abstain_score: float) -> None:
    """Kanıt kapısı bu sağlayıcıyla ANLAMLI mı — değilse AÇILIŞTA hata.

    `abstain_score` eşiği yerel BGE reranker'ın skor dağılımı üzerinde ölçüldü
    (EXP-017). Skorları kalibre olmayan bir sağlayıcıyla aynı eşiği kullanmak,
    fail-closed kapıyı SESSİZCE devre dışı bırakır: ürün her soruya cevap
    üretmeye çalışır ve "kaynaklarda bulamadım" davranışı kaybolur.

    Eşik zaten kapalıysa (`abstain_score <= 0`) sorun yok — operatör kapıyı
    bilerek kapatmış demektir.

    `RAG_ALLOW_UNCALIBRATED_ABSTAIN=1` ile bilinçli olarak geçilebilir; bu
    bayrak "riski biliyorum" beyanıdır, varsayılan değildir.
    """
    if abstain_score <= 0:
        return
    if getattr(reranker, "calibrated_scores", True):
        return
    if ALLOW_UNCALIBRATED:
        return
    raise RuntimeError(
        f"{type(reranker).__name__} skorlari cekimserlik esigi icin KALIBRE "
        f"DEGIL, ama abstain_score={abstain_score} etkin. Esik yerel BGE "
        "reranker'in skor dagilimi uzerinde olculdu (EXP-017); baska bir "
        "saglayicida kapi HIC tetiklenmez ve urun kitapta olmayan soruya da "
        "cevap uretmeye calisir. Secenekler: (1) esigi bu saglayici icin "
        "yeniden kalibre et (python -m src.eval.calibrate_abstain_cli), "
        "(2) RAG_ABSTAIN_SCORE=0 ile kapiyi bilerek kapat, "
        "(3) riski kabul ediyorsan RAG_ALLOW_UNCALIBRATED_ABSTAIN=1.")


def provider_warnings(reranker) -> list:
    """Seçimin ölçülmüş bedelleri — açılışta söylenir."""
    u = []
    if isinstance(reranker, NoOpReranker):
        u.append("Rerank KAPALI (RAG_RERANK_PROVIDER=off) → aday sırası RRF'ten "
                 "geliyor. Bu seçenek ölçümle DESTEKLENMİŞ DEĞİLDİR: mevcut "
                 "golden set reranker'ın aleyhine kuruludur (sorgular birimin "
                 "kendi metni), o yüzden 'rerank gereksiz' sonucu çıkarılamaz "
                 "(#91).")
    if not getattr(reranker, "calibrated_scores", True):
        u.append("Rerank skorları çekimserlik eşiği için KALİBRE DEĞİL → "
                 "fail-closed kanıt kapısı bu sağlayıcıda anlamsız. EXP-017 "
                 "kalibrasyonu bu sağlayıcı için tekrar koşulmalı.")
    return u
