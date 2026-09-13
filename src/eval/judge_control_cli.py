"""#72 — hakem negatif/pozitif kontrol koşumu.

  .venv/bin/python -m src.eval.judge_control_cli --n 20

Hakem GEÇTİ/KALDI demez; ayırt etme gücünü ölçer ve rapor yazar. Kararı
insan verir (#91).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Hakem kontrol kosumu")
    ap.add_argument("--golden", default="tests/golden/golden_10biy_v2.json")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL",
                                                           "deepseek-chat"))
    ap.add_argument("--out-dir", default="tests/evaluation/results")
    a = ap.parse_args(argv)

    from .judge import LlmJudge
    from .judge_control import build_controls, run_controls
    from .runner import _load_dotenv

    _load_dotenv()          # API anahtari .env'den (runner ile ayni yol)

    if not os.path.isfile(a.golden):
        print(f"[hata] golden set yok: {a.golden}", file=sys.stderr)
        return 2
    items = json.load(open(a.golden, encoding="utf-8"))["items"]
    cases = build_controls(items, n=a.n)
    if not cases:
        print("[hata] kontrol vakasi uretilemedi", file=sys.stderr)
        return 2
    print(f"[hakem] {len(cases)} vaka · model={a.judge_model}", flush=True)

    t0 = time.time()
    report = run_controls(LlmJudge(model_name=a.judge_model), cases)
    sure = time.time() - t0

    out = report.to_dict()
    out["meta"] = {"judge_model": a.judge_model, "golden": a.golden,
                   "seconds": round(sure, 1)}
    os.makedirs(a.out_dir, exist_ok=True)
    damga = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    yol = os.path.join(a.out_dir, f"judge_control_{damga}.json")
    with open(yol, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n{'metrik':<22}{'pozitif':>10}{'negatif':>10}{'ayrim':>10}")
    for m in ("faithfulness", "groundedness", "answer_relevancy",
              "answer_correctness"):
        p = report.positive[m]["mean"]
        n = report.negative[m]["mean"]
        d = report.discrimination[m]
        f2 = lambda v: f"{v:.3f}" if isinstance(v, float) else "     -"
        print(f"{m:<22}{f2(p):>10}{f2(n):>10}{f2(d):>10}")
    print("\nbozma turu kirilimi (YALNIZ hedeflenen metrik):")
    for k, d in sorted(report.by_kind.items()):
        for m, v in d.items():
            print(f"  {k:<18}{m:<20}n={v['n']:<3}"
                  f"ort={v['mean'] if v['mean'] is None else round(v['mean'], 3)}")
    if report.errors:
        print(f"\n[UYARI] {len(report.errors)} hata:")
        for e in report.errors[:8]:
            print("   ", e[:120])
    print(f"\n[hakem] {sure:.1f}s · JSON: {yol}")
    print("[hakem] KARAR VERILMEDI -- ayirt etme gucu olculdu, yorum insana ait.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
