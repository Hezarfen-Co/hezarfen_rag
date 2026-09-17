"""Sağlayıcı yapılandırmasının AÇILIŞ ÖN DENETİMİ — fail-closed.

NEDEN VAR (ölçülmüş sınıf): gömme/rerank API sağlayıcısına alındığında eksik
bir anahtar ya da taban adresi AÇILIŞTA görünmüyordu. Konteyner ayağa kalkıyor,
`/health` ok dönüyor, `/ready` "hazır" diyor ve İLK gerçek soru
`EmbeddingUnavailable`/401 ile düşüyordu — yani "çalışıyor gibi görünen, hiçbir
isteğe cevap veremeyen servis". Deploy açısından bu, hiç kalkmayan servisten
KÖTÜdür: kapı yeşil geçer, ürün ölü olur.

Bu modül seçili sağlayıcıların ZORUNLU adlarını denetler, eksiği ADIYLA söyler
ve `create_app_with_warmup` içinden çağrıldığı için uvicorn daha portu
dinlemeden süreci durdurur (`SystemExit(2)` → konteyner çıkar, /health hiç ok
dönmez, deploy kapısı rollback yapar).

ANAHTAR İKİ BİÇİMDE VERİLEBİLİR — bu, kodun GERÇEK mekanizmasıdır; ikinci bir
yol uydurulmadı (`src/embed/provider.py`, `src/rerank/provider.py`):

    RAG_EMBED_API_KEY=<değer>             doğrudan
    RAG_EMBED_API_KEY_ENV=<DEĞİŞKEN>      dolaylı: <DEĞİŞKEN> okunur

SEÇİM VE ANAHTAR ADI modüllerden okunur (`_embed.PROVIDER`, `_embed.API_KEY_ENV`):
bunlar İÇE AKTARMA anında ortamdan dondurulan değerlerdir ve istemcilerin
(`ApiEmbedder`/`ApiReranker`) gerçekten kullanacağı değerlerin TA KENDİSİDİR.
Taze bir `os.environ` okuması, kodun kullanmadığı bir seçimi "geçerli" sayabilir.

Çalıştırma (elle / dağıtım öncesi):

    python -m src.service.preflight          # `--validate` de aynı şeyi yapar
"""
from __future__ import annotations

import os
import sys
from typing import Mapping

from ..embed import provider as _embed
from ..generate.generator import ABSTAIN_SCORE_DEFAULT
from ..providers.llm import LLM_API_KEY_ENV
from ..rerank import provider as _rerank

#: Dağıtım varsayılanı (API yolu). `Containerfile` `ENV` bloğu ve
#: `deploy/hezarfen_rag.env.example` bu değerleri taşımak ZORUNDADIR;
#: `tests/unit/test_providers_deploy.py` üçünü bu sabitle karşılaştırır.
#:
#: KOD İÇİ fabrika varsayılanı (`local`) DEĞİŞMEZ: ölçülmüş bütün kalite
#: sayıları (EXP-011/013/017/018) yerel yola aittir ve değerlendirme koşuları
#: env'siz çalışır. Ayrım bilinçli: "kod varsayılanı" ölçüm/yerel geliştirme,
#: "dağıtım varsayılanı" 7,6 GiB'lik GPU'suz sunucudur.
DEPLOY_DEFAULT_PROVIDERS = {
    "RAG_EMBED_PROVIDER": "api",
    "RAG_RERANK_PROVIDER": "api",
}

#: `build_reranker`/`build_embedder` ile AYNI sözlük (kaynak: provider.py).
_EMBED_LOCAL = ("local", "", "bge", "bgem3")
_RERANK_LOCAL = ("local", "", "bge")
_RERANK_OFF = ("off", "none", "yok")

#: YEREL YOL = EKLENTİ VOLUME (küçük imge kararı, 2026-09-17). Varsayılan imge
#: torch/FlagEmbedding TAŞIMAZ; yerel bağımlılıklar volume içindeki bir venv'de,
#: ağırlıklar ayrı bir dizinde (HF_HOME) yaşar ve .env ile seçilir — imgeyi
#: yeniden derlemek ya da workflow koşmak GEREKMEZ.
LOCAL_VENV_ENV = "RAG_LOCAL_VENV"
LOCAL_MODELS_ENV = "RAG_LOCAL_MODELS_DIR"
#: Sağlama: `deploy/provision_local_stack.sh` (idempotent, bir kez çalıştırılır).
LOCAL_PROVISION_SCRIPT = "deploy/provision_local_stack.sh"


LOCAL_MARKER = "PROVISIONED"


def yerel_yigin_durumu(env: Mapping[str, str] | None = None) -> str:
    """Volume'daki sağlama işareti: 'yok' ya da 'image=.. tag=.. python=..'.

    Sağlama (`deploy/provision_local_stack.sh`) volume'a `PROVISIONED` yazar;
    böylece 'sağlanmış mı' sorusu tahminle değil dosyayla cevaplanır.
    """
    env = os.environ if env is None else env
    kok = _deger(env, LOCAL_VENV_ENV)
    if not kok:
        return "yok"
    yol = os.path.join(os.path.dirname(kok.rstrip("/")), LOCAL_MARKER)
    try:
        with open(yol, encoding="utf-8") as fh:
            alanlar = dict(s.split("=", 1) for s in fh.read().split() if "=" in s)
    except OSError:
        return f"yok ({LOCAL_MARKER} bulunamadı: {yol})"
    return (f"image={alanlar.get('PROVISIONED_IMAGE', '?')} "
            f"tag={alanlar.get('PROVISIONED_TAG', '?')} "
            f"python={alanlar.get('PYTHON', '?')} "
            f"date={alanlar.get('DATE', '?')}")


def _yerel_yigin_site_packages(env: Mapping[str, str]) -> list[str]:
    """`RAG_LOCAL_VENV` içindeki site-packages dizinleri (yoksa [])."""
    import glob
    kok = _deger(env, LOCAL_VENV_ENV)
    if not kok:
        return []
    return sorted(set(glob.glob(os.path.join(kok, "lib", "python3.*", "site-packages"))
                      + glob.glob(os.path.join(kok, "lib64", "python3.*", "site-packages"))))


def yerel_yigin_hazirla(env: Mapping[str, str] | None = None) -> list[str]:
    """Yerel yığını HAZIRLAR: volume venv'ini `sys.path`e ekler, HF_HOME'u
    volume'daki ağırlık dizinine çevirir. Eksikleri (varsa) döndürür.

    İmge küçüktür: torch/transformers imajdan DEĞİL, takılı volume'dan gelir.
    """
    env = os.environ if env is None else env
    eksik: list[str] = []
    sp = _yerel_yigin_site_packages(env)
    if sp:
        for d in reversed(sp):
            if d not in sys.path:
                sys.path.insert(0, d)
    agirlik = _deger(env, LOCAL_MODELS_ENV)
    if agirlik:
        # Ağırlıklar da volume'da kalsın (restart'ta yeniden inmesin).
        os.environ["HF_HOME"] = agirlik
    return eksik


def yerel_yigin_eksik(env: Mapping[str, str] | None = None) -> list[str]:
    """`local` seçiliyken yığın nereden gelecek — eksikse ADIYLA söyler."""
    env = os.environ if env is None else env
    import importlib.util
    sp = _yerel_yigin_site_packages(env)
    if sp:
        if importlib.util.find_spec("torch") is not None:
            return []
        return [f"{LOCAL_VENV_ENV}={_deger(env, LOCAL_VENV_ENV)!r} içinde torch "
                "bulunamadı — sağlama yarım kalmış (işaret: "
                f"{yerel_yigin_durumu(env)}). Tekrar çalıştır: bash "
                f"{LOCAL_PROVISION_SCRIPT} && systemctl --user restart "
                "hezarfen_rag_compose"]
    if importlib.util.find_spec("torch") is not None:
        return []          # geliştirme/CI makinesi: yığın zaten kurulu
    return [f"yerel model yığını (torch/FlagEmbedding) ne imajda ne volume'da var"
            f" — bu imaj KÜÇÜK (API yolu) derlendi (yerel işaret: "
            f"{yerel_yigin_durumu(env)}). Yerel yola geçmek için: (1) volume'u bir "
            f"kez sağla -> `bash {LOCAL_PROVISION_SCRIPT}`, (2) .env'e "
            f"{LOCAL_VENV_ENV}=/local-stack/venv ve {LOCAL_MODELS_ENV}="
            "/local-stack/models yaz, (3) `systemctl --user restart "
            "hezarfen_rag_compose`. Alternatif: imajı `podman build --build-arg "
            "WITH_LOCAL_MODELS=1` ile derle, ya da provider'ları `api` bırak"]


def _deger(env: Mapping[str, str], ad: str) -> str:
    """Boş/boşluk değer AYARSIZ sayılır (`.env` boş satır bırakabiliyor)."""
    return (env.get(ad) or "").strip()


def _anahtar_eksik(env: Mapping[str, str], ad: str, isaretci: str,
                   katman: str) -> list[str]:
    """API anahtarı var mı — doğrudan ad ya da `*_API_KEY_ENV` yönlendirmesi.

    `ad` modülden gelir (`API_KEY_ENV`), yani dolaylı ad verilmişse o adın
    kendisidir; burada ikinci bir çözümleme yapılmaz.
    """
    if not ad:
        return [f"{isaretci} boş — {katman} API anahtarının okunacağı ad yok"]
    if _deger(env, ad):
        return []
    if ad == isaretci:                  # doğrudan ad (yönlendirme kullanılmadı)
        return [f"{ad} boş ({katman} API anahtarı yok; ya da "
                f"{isaretci}=<DEĞİŞKEN> ile dolaylı ver)"]
    return [f"{ad} boş ({katman} API anahtarı yok; ad {isaretci} ile verildi)"]


def check_provider_config(env: Mapping[str, str] | None = None) -> list[str]:
    """Eksik/uygunsuz yapılandırmayı ADIYLA listeler; her şey tamsa `[]`.

    `env` yalnız DEĞERLER için kullanılır (testler buradan besler). Seçim
    (`RAG_EMBED_PROVIDER` / `RAG_RERANK_PROVIDER`) ve anahtar adı, çalışma
    zamanındaki istemcilerin kullandığı modül sabitlerinden okunur.
    """
    env = os.environ if env is None else env
    eksik: list[str] = []

    # --- gömme -----------------------------------------------------------
    emb = (getattr(_embed, "PROVIDER", "local") or "").strip().lower()
    if emb in _EMBED_LOCAL:
        # Yerel model: API anahtarı gerekmez AMA yığın bir yerden gelmeli
        # (küçük imge onu taşımaz → volume ya da geliştirme makinesi).
        eksik.extend(yerel_yigin_eksik(env))
    elif emb == "api":
        for ad in ("RAG_EMBED_API_BASE", "RAG_EMBED_MODEL"):
            if not _deger(env, ad):
                eksik.append(f"{ad} boş (RAG_EMBED_PROVIDER=api için zorunlu)")
        eksik.extend(_anahtar_eksik(env, getattr(_embed, "API_KEY_ENV", ""),
                                    "RAG_EMBED_API_KEY_ENV", "gömme"))
    else:
        eksik.append(f"RAG_EMBED_PROVIDER={emb!r} tanınmıyor "
                     "(geçerli: local | api)")

    # --- rerank ----------------------------------------------------------
    rr = (getattr(_rerank, "PROVIDER", "local") or "").strip().lower()
    if rr in _RERANK_LOCAL:
        eksik.extend(yerel_yigin_eksik(env))
    elif rr == "api":
        for ad in ("RAG_RERANK_API_URL", "RAG_RERANK_MODEL"):
            if not _deger(env, ad):
                eksik.append(f"{ad} boş (RAG_RERANK_PROVIDER=api için zorunlu)")
        eksik.extend(_anahtar_eksik(env, getattr(_rerank, "API_KEY_ENV", ""),
                                    "RAG_RERANK_API_KEY_ENV", "rerank"))
    elif rr not in _RERANK_OFF:
        eksik.append(f"RAG_RERANK_PROVIDER={rr!r} tanınmıyor "
                     "(geçerli: local | api | off)")

    # --- çekimserlik kapısı (fail-closed kanıt kapısı) --------------------
    # Sağlayıcının KENDİ eksiği (uç nokta vb.) yukarıda rapor edildi; kurucu bu
    # yüzden patlarsa yeniden raporlamayız (kapı, eksik giderildikten SONRA
    # görünür — sessizce yeşile dönmez). Değerler `env`den AÇIKÇA geçirilir:
    # istemci aksi halde modül sabitlerine düşerdi ve denetim, denetlediğini
    # sandığı yapılandırmadan başkasına bakmış olurdu.
    if rr in _RERANK_LOCAL or rr in _RERANK_OFF or rr == "api":
        kw = ({"url": _deger(env, "RAG_RERANK_API_URL") or None,
               "model": _deger(env, "RAG_RERANK_MODEL") or None,
               "api_key": _deger(env, "RAG_RERANK_API_KEY") or None}
              if rr == "api" else {})
        try:
            aday = _rerank.build_reranker(provider=rr, **kw)
        except ValueError:
            aday = None
        if aday is not None:
            try:
                _rerank.check_abstain_compatibility(
                    aday, abstain_score=ABSTAIN_SCORE_DEFAULT)
            except RuntimeError as e:
                eksik.append(str(e).splitlines()[0])

    # --- üretici LLM -----------------------------------------------------
    # Eksikse HER sohbet çağrısı düşer; /ready yeşil kalır (ölçüldü: anahtar
    # yalnız `chat()` anında okunuyor). Aynı sessiz-sınıf: açılışta söylenir.
    if not _deger(env, LLM_API_KEY_ENV):
        eksik.append(f"{LLM_API_KEY_ENV} boş (her /rag/chat çağrısı için zorunlu)")

    # Yerel yığın eksiği hem gömme hem rerank dalında sorulur: aynı satırı
    # iki kez yazmak operatöre gürültüdür (sıra korunur).
    return list(dict.fromkeys(eksik))


def report(eksik: list[str]) -> str:
    """Operatörün tek bakışta okuyacağı ret metni (sır YAZILMAZ)."""
    satirlar = [
        "[preflight] YAPILANDIRMA REDDEDİLDİ — servis bu hâlde AYAĞA KALKMAZ.",
        f"[preflight] eksik/uygunsuz {len(eksik)} ad:",
    ]
    satirlar += [f"[preflight]   {i}. {m}" for i, m in enumerate(eksik, 1)]
    satirlar.append(
        "[preflight] Şablon: deploy/hezarfen_rag.env.example (sunucuda "
        "~/hezarfen_rag/hezarfen_rag.env). Yerel sağlayıcılara dönmek için "
        "RAG_EMBED_PROVIDER=local / RAG_RERANK_PROVIDER=local + modellerin "
        "bulunduğu bir HF_HOME ver.")
    return "\n".join(satirlar)


def enforce(env: Mapping[str, str] | None = None) -> None:
    """Eksik varsa raporu basıp süreci DURDURUR (uygulama açılışında çağrılır)."""
    yerel_yigin_hazirla(env)      # sys.path/HF_HOME: volume'daki yerel yığın
    eksik = check_provider_config(env)
    if eksik:
        print(report(eksik), file=sys.stderr, flush=True)
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m src.service.preflight [--validate]`."""
    argv = list(sys.argv[1:] if argv is None else argv)
    for arg in argv:
        if arg not in ("--validate",):
            print(f"[preflight] bilinmeyen argüman: {arg!r} (geçerli: --validate)",
                  file=sys.stderr)
            return 2
    yerel_yigin_hazirla()
    eksik = check_provider_config()
    if eksik:
        print(report(eksik), file=sys.stderr)
        return 2
    emb = (getattr(_embed, "PROVIDER", "local") or "local").strip().lower()
    rr = (getattr(_rerank, "PROVIDER", "local") or "local").strip().lower()
    print(f"[preflight] tamam — gömme={emb} rerank={rr} "
          f"cekimserlik_esigi={ABSTAIN_SCORE_DEFAULT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
