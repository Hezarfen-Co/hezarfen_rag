"""#60 — çekimserlik eşiği kalibrasyon koşumu.

  .venv/bin/python -m src.eval.calibrate_abstain_cli

LLM ÇAĞIRMAZ ($0): eşik zaten LLM'den ÖNCE karar verir. Ayar DEV yarısında,
rapor FROZEN yarısında (#M3-8/EVAL-11). Eşik SEÇMEZ — ödünleşim eğrisini ve
aday işletme noktalarını verir; kararı insan alır.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


def _tablo(points, esikler):
    print(f"\n{'esik':>6}{'yanlis cekimser':>18}{'yanlis cevap':>16}")
    for p in points:
        if round(p.threshold, 4) not in esikler:
            continue
        d = p.to_dict()
        fa, fc = d["false_abstention_rate"], d["false_answer_rate"]
        f = lambda v: "     -" if v is None else f"{v:6.3f}"
        print(f"{p.threshold:6.2f}{f(fa):>18}{f(fc):>16}"
              f"   ({p.false_abstentions}/{p.n_answerable}, "
              f"{p.false_answers}/{p.n_unanswerable})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cekimserlik esigi kalibrasyonu")
    ap.add_argument("--golden", default="tests/golden/golden_10biy_v2.json")
    ap.add_argument("--book", default=None)
    ap.add_argument("--out-dir", default="tests/evaluation/results")
    ap.add_argument("--max-false-abstention", type=float, default=0.05)
    a = ap.parse_args(argv)

    from .abstain_calibration import candidates, collect_scores, report
    from .golden_schema import split_dev_frozen
    from .runner import BOOK_PATH, build_pipeline

    if not os.path.isfile(a.golden):
        print(f"[hata] golden set yok: {a.golden}", file=sys.stderr)
        return 2
    items = json.load(open(a.golden, encoding="utf-8"))["items"]
    dev, frozen = split_dev_frozen(items)
    print(f"[kalibrasyon] dev={len(dev)} frozen={len(frozen)}", flush=True)

    pipeline = build_pipeline(a.book or BOOK_PATH)
    gen = pipeline["generator"]

    t0 = time.time()
    sonuc = {}
    for ad, kume in (("dev", dev), ("frozen", frozen)):
        print(f"\n[kalibrasyon] {ad} kumesi ({len(kume)} item) olculuyor...",
              flush=True)

        def ilerle(i, n, s, _ad=ad):
            if i % 20 == 0 or i == n:
                print(f"  {_ad} {i}/{n}", flush=True)

        skorlar = collect_scores(gen, kume, on_progress=ilerle)
        r = report(skorlar)
        sonuc[ad] = r

    dev_rapor, frozen_rapor = sonuc["dev"], sonuc["frozen"]
    adaylar = candidates(dev_rapor.points,
                         max_false_abstention=a.max_false_abstention)

    print("\n=== DEV (ayar burada yapilir) ===")
    _tablo(dev_rapor.points, {0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8})
    print("\nsenaryo bazinda tepe skor dagilimi (dev):")
    for k, v in dev_rapor.by_scenario.items():
        print(f"  {k:<16}n={v['n']:<4}min={v['min']:<8}p10={v['p10']:<8}"
              f"medyan={v['median']:<8}max={v['max']}")

    print("\n=== ADAY ISLETME NOKTALARI (dev uzerinde) ===")
    for ad, d in adaylar.items():
        if d is None:
            print(f"  {ad:<34} YOK (kisiti saglayan esik bulunamadi)")
            continue
        print(f"  {ad:<34} esik={d['threshold']:.2f}  "
              f"yanlis_cekimser={d['false_abstention_rate']}  "
              f"yanlis_cevap={d['false_answer_rate']}")

    print("\n=== FROZEN (yalniz RAPOR -- burada ayar YAPILMAZ) ===")
    ilgi = {round(d["threshold"], 4) for d in adaylar.values() if d}
    ilgi.add(0.30)                      # bugunku uretim varsayilani
    _tablo(frozen_rapor.points, ilgi)

    os.makedirs(a.out_dir, exist_ok=True)
    damga = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    yol = os.path.join(a.out_dir, f"abstain_calibration_{damga}.json")
    with open(yol, "w", encoding="utf-8") as f:
        json.dump({"meta": {"golden": a.golden, "seconds": round(time.time() - t0, 1),
                            "current_default": 0.30,
                            "max_false_abstention": a.max_false_abstention},
                   "dev": dev_rapor.to_dict(), "frozen": frozen_rapor.to_dict(),
                   "candidates": adaylar}, f, ensure_ascii=False, indent=2)
    print(f"\n[kalibrasyon] {time.time() - t0:.1f}s · JSON: {yol}")
    print("[kalibrasyon] ESIK SECILMEDI -- odunlesim olculdu, karar insana ait.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
