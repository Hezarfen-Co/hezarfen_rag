"""EBA materyal indirici — katalogdan diske, devam ettirilebilir.

Koşum:
  .venv/bin/python -m src.corpus.eba_download --mufredat guncel
  .venv/bin/python -m src.corpus.eba_download --sinif 11 --ders biyoloji --limit 5

Yerleşim: `data/<kasa>/<sınıf>/<ders>/eba/<dosya>.pdf` + aynı klasörde
`eba-index.json` (her dosyanın sınıf/ders/ünite/kazanım/başlık bilgisi).

Tasarım kararları:
- **Devam ettirilebilir:** var olan ve boyutu makul dosya atlanır. Yarıda kesilen
  bir indirme yeniden başlatılınca baştan almaz.
- **Atomik yazım:** önce `.tmp`, sonra `os.replace`. Yarım dosya, "var" sayılıp
  bir daha indirilmemesine yol açardı.
- **Kibarlık:** istekler arası bekleme (varsayılan 0,4 s) ve tek akış. Bu bir
  kamu eğitim sunucusu; paralel yüklemekten kaçınılır.
- **Disk koruması:** boş alan eşiğin altına inerse durur.
- **Kazanım indeksi:** dosyanın yanına yazılır. #94'te görüldüğü gibi kitap ile
  kazanımın ayrışması sessiz bir ölçüm hatasına yol açıyor; burada kazanım
  materyalin KENDİSİNDEN gelir, ayrı bir dosyadan tahmin edilmez.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from .eba_catalog import Material, fetch_bundle, parse_bundle, summary

MIN_FREE_GB = 5.0
SLEEP = 0.4
ROOT = os.environ.get("EBA_VAULT") or "data"


def vault_for(sinif: str | None) -> str | None:
    if not sinif:
        return None
    n = int(sinif)
    return "ortaokul" if 5 <= n <= 8 else ("lise" if 9 <= n <= 12 else None)


def free_gb(yol: str = ".") -> float:
    p = yol
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    return shutil.disk_usage(p or ".").free / 1024 ** 3


def target_dir(m: Material, *, kok: str = ROOT) -> str | None:
    kasa = vault_for(m.sinif)
    if not (kasa and m.ders):
        return None
    return os.path.join(kok, kasa, m.sinif, m.ders, "eba")


def file_name(m: Material) -> str:
    ad = m.pdf_url.rsplit("/", 1)[-1].split("?")[0]
    return ad if ad.lower().endswith(".pdf") else ad + ".pdf"


def download(oturum, url: str, hedef: str, *, min_bayt: int = 2048,
          timeout: float = 120.0) -> tuple[str, int]:
    """('atlandi'|'indi'|'kucuk', bayt). Atomik: önce .tmp, sonra replace."""
    if os.path.exists(hedef) and os.path.getsize(hedef) >= min_bayt:
        return "atlandi", os.path.getsize(hedef)
    os.makedirs(os.path.dirname(hedef), exist_ok=True)
    tmp = hedef + ".tmp"
    with oturum.get(url, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        n = 0
        with open(tmp, "wb") as fh:
            for parca in r.iter_content(65536):
                fh.write(parca)
                n += len(parca)
    if n < min_bayt:
        os.remove(tmp)
        return "kucuk", n
    os.replace(tmp, hedef)
    return "indi", n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EBA materyallerini download")
    ap.add_argument("--mufredat", default="guncel",
                    choices=("guncel", "2017-23", "hepsi"))
    ap.add_argument("--sinif", action="append", help="9/10/11/12 (birden çok kez)")
    ap.add_argument("--ders", action="append", help="korpus slug'ı (birden çok kez)")
    ap.add_argument("--limit", type=int, help="ders başına en çok N dosya")
    ap.add_argument("--kok", default=ROOT)
    ap.add_argument("--bekleme", type=float, default=SLEEP)
    ap.add_argument("--sadece-listele", action="store_true")
    a = ap.parse_args(argv)

    import requests
    s = requests.Session()
    print("[catalog] bundle indiriliyor...", flush=True)
    mats = parse_bundle(fetch_bundle(s))
    o = summary(mats)
    print(f"[catalog] {o['toplam']} kayıt, {o['benzersiz_pdf']} benzersiz pdf, "
          f"{o['kazanimli']} kazanım kodlu", flush=True)

    secili = [m for m in mats if target_dir(m, kok=a.kok)]
    if a.mufredat != "hepsi":
        secili = [m for m in secili if m.mufredat == a.mufredat]
    if a.sinif:
        secili = [m for m in secili if m.sinif in set(a.sinif)]
    if a.ders:
        secili = [m for m in secili if m.ders in set(a.ders)]

    # aynı pdf birden çok kayıtta geçebilir; ilk kaydı tut
    gorulen, benzersiz = set(), []
    for m in secili:
        if m.pdf_url in gorulen:
            continue
        gorulen.add(m.pdf_url)
        benzersiz.append(m)

    # ders başına limit
    if a.limit:
        sayac, kirpilmis = {}, []
        for m in benzersiz:
            k = (m.sinif, m.ders)
            if sayac.get(k, 0) >= a.limit:
                continue
            sayac[k] = sayac.get(k, 0) + 1
            kirpilmis.append(m)
        benzersiz = kirpilmis

    import collections
    dagilim = collections.Counter(f"{m.sinif}/{m.ders}" for m in benzersiz)
    print(f"[plan] {len(benzersiz)} dosya · {len(dagilim)} sınıf-ders", flush=True)
    for k, v in sorted(dagilim.items()):
        print(f"   {k:22} {v}", flush=True)
    if a.sadece_listele:
        return 0

    indeksler: dict[str, list[dict]] = {}
    indi = atlandi = hata = 0
    t0 = time.time()
    for i, m in enumerate(benzersiz, 1):
        if free_gb(a.kok) < MIN_FREE_GB:
            print(f"[dur] boş alan {MIN_FREE_GB} GB altına indi", flush=True)
            break
        d = target_dir(m, kok=a.kok)
        hedef = os.path.join(d, file_name(m))
        try:
            durum, n = download(s, m.pdf_url, hedef)
        except Exception as e:
            hata += 1
            print(f"  ! {m.sinif}/{m.ders} {file_name(m)}: {type(e).__name__} {e}",
                  flush=True)
            continue
        if durum == "indi":
            indi += 1
        elif durum == "atlandi":
            atlandi += 1
        kayit = m.to_dict()
        kayit["dosya"] = file_name(m)
        indeksler.setdefault(d, []).append(kayit)
        if i % 50 == 0:
            print(f"[{i}/{len(benzersiz)}] indi={indi} atlandi={atlandi} "
                  f"hata={hata} süre={time.time()-t0:.0f}s", flush=True)
        if durum == "indi":
            time.sleep(a.bekleme)

    for d, kayitlar in indeksler.items():
        yol = os.path.join(d, "eba-index.json")
        eski = []
        if os.path.isfile(yol):
            try:
                with open(yol, encoding="utf-8") as fh:
                    eski = json.load(fh)
            except Exception:
                eski = []
        birlesik = {k["pdf_url"]: k for k in eski}
        birlesik.update({k["pdf_url"]: k for k in kayitlar})
        with open(yol, "w", encoding="utf-8") as fh:
            json.dump(sorted(birlesik.values(),
                             key=lambda k: (k.get("unite") or "", k.get("dosya") or "")),
                      fh, ensure_ascii=False, indent=2)

    print(f"\n[bitti] indi={indi} atlandi={atlandi} hata={hata} "
          f"süre={time.time()-t0:.0f}s boş={free_gb(a.kok):.1f}GB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
