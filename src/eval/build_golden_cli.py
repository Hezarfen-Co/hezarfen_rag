"""Golden set v2 üretim CLI'si.

Koşum:
  .venv/bin/python -m src.eval.build_golden_cli --sinif 10 --ders biyoloji

Üretim DETERMİNİSTİKTİR (sabit tohum): aynı korpustan aynı set çıkar.
Şema geçersizse **yazmaz** — pass-bias yasak.
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Golden set v2 uret")
    ap.add_argument("--sinif", default="10")
    ap.add_argument("--ders", default="biyoloji")
    ap.add_argument("--kok", default="data")
    ap.add_argument("--kasa", default="lise")
    ap.add_argument("--out", default=None)
    ap.add_argument("--seed", type=int, default=20260913)
    a = ap.parse_args(argv)

    from ..ingest.canonical import build_canonical
    from ..demo.scenario import read_objectives, covered_objectives
    from .golden_build import build, in_domain_unanswerable, write

    kitap = os.path.join(a.kok, a.kasa, a.sinif, a.ders, "kitap.pdf")
    if not os.path.isfile(kitap):
        print(f"[hata] kitap yok: {kitap}", file=sys.stderr)
        return 2
    print(f"[golden] {kitap} ayristiriliyor...", flush=True)
    doc = build_canonical(kitap, sinif=a.sinif, ders=a.ders)

    hepsi = read_objectives(a.kok, a.kasa, a.sinif, a.ders)
    kapsanan = {k["kod"] for k in covered_objectives(a.kok, a.kasa, a.sinif, a.ders)}
    kapsanmayan = [k for k in hepsi if k.get("kod") not in kapsanan]
    cevapsiz = in_domain_unanswerable(a.kok, a.kasa, a.sinif, a.ders, kapsanmayan)
    print(f"[golden] kazanim={len(hepsi)} kapsanmayan={len(kapsanmayan)} "
          f"alan-ici-cevapsiz={len(cevapsiz)}", flush=True)

    kapsanan_liste = [k for k in hepsi if k.get("kod") in kapsanan]
    items = build(doc, objectives=hepsi, uncovered=cevapsiz,
                  kapsanan_objectives=kapsanan_liste, seed=a.seed,
                  n_global=22, n_unanswerable=22)
    yol = a.out or os.path.join("tests", "golden",
                                f"golden_{a.sinif}{a.ders[:3]}_v2.json")
    sonuc = write(items, yol, sinif=a.sinif, ders=a.ders)
    print(f"[golden] {sonuc['n']} item -> {sonuc['path']} "
          f"(uyari: {sonuc['warnings']})", flush=True)
    for k, v in sorted(sonuc["distribution"].items(), key=lambda x: -x[1]):
        print(f"    {k:15} %{v*100:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
