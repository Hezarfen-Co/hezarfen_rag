#!/usr/bin/env python3
"""Discover EBA (ogmmateryal.eba.gov.tr) grade/subject code map -> eba_codes.json

Site = Ortaogretim Genel Mudurlugu (OGM) => HIGH SCHOOL ONLY (grades 9-12).
Grade query-param code = grade - 3  (code6=9, code7=10, code8=11, code9=12).
Grade code 4 = a special standalone "Matematik" (d=65).
Subject 'd' code is per-grade (Matematik: 48/49/50/51 for grades 9-12).

Three per-flow subject endpoints (POST, JSON [{id,baslik,kod,urlKod,...}]):
  soru    /api/soru-ders-listele/{gc}     -> C (kazanim) + D (questions)
  fasikul /api/fasikul-ders-listele/{gc}  -> A (konu ozetleri)   [urlKod is null here]
  calisma /api/calisma-ders-listele/{gc}  -> B (calisma defteri)
"""
import requests, json, time, os

BASE = "https://ogmmateryal.eba.gov.tr"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "eba_codes.json")

FLOWS = {
    "soru":    "/api/soru-ders-listele/",
    "fasikul": "/api/fasikul-ders-listele/",
    "calisma": "/api/calisma-ders-listele/",
}
GRADE_CODES = [4, 6, 7, 8, 9]
CODE2GRADE = {6: 9, 7: 10, 8: 11, 9: 12}   # 4 = special

# site urlKod slug -> vault folder slug (keep consistent with book folders)
VAULT_SLUG = {
    "tde": "turk-dili-edebiyat",
    "inkilap-tarihi": "inkilap",
    "dikab": "din-kulturu",
}

def vault_slug(slug):
    return VAULT_SLUG.get(slug, slug)

def main():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Content-Type": "application/json; charset=utf-8"})

    # flow -> gc -> [records]
    raw = {f: {} for f in FLOWS}
    for flow, ep in FLOWS.items():
        for gc in GRADE_CODES:
            r = s.post(BASE + ep + str(gc), data="{}", timeout=25)
            try:
                arr = r.json()
            except Exception:
                arr = []
            raw[flow][gc] = arr if isinstance(arr, list) else []
            time.sleep(0.3)

    # slug lookup by subject id (soru/calisma have urlKod; fasikul is null)
    slug_by_id = {}
    for flow in ("soru", "calisma"):
        for gc, arr in raw[flow].items():
            for d in arr:
                if d.get("urlKod"):
                    slug_by_id[d["id"]] = d["urlKod"]

    subjects = {}     # gc -> [ {id, baslik, kod, slug, vault_slug, flows} ]
    for gc in GRADE_CODES:
        by_id = {}
        for flow in FLOWS:
            for d in raw[flow].get(gc, []):
                e = by_id.setdefault(d["id"], {
                    "id": d["id"],
                    "baslik": d["baslik"],
                    "kod": d.get("kod"),
                    "slug": d.get("urlKod") or slug_by_id.get(d["id"]),
                    "flows": [],
                })
                if not e["slug"] and d.get("urlKod"):
                    e["slug"] = d["urlKod"]
                e["flows"].append(flow)
        for e in by_id.values():
            e["slug"] = e["slug"] or slug_by_id.get(e["id"])
            e["vault_slug"] = vault_slug(e["slug"]) if e["slug"] else None
        subjects[str(gc)] = sorted(by_id.values(), key=lambda x: x["id"])

    out = {
        "_note": "ogmmateryal.eba.gov.tr = OGM (high school only, grades 9-12). "
                 "Grade query code = grade-3. Subject 'd' code is per-grade. "
                 "Grade code 4 = standalone Matematik (d=65).",
        "base": BASE,
        "cdn": "https://ogm-large-cdn.eba.gov.tr",
        "grade_code_to_grade": {str(k): v for k, v in CODE2GRADE.items()} | {"4": "ozel-matematik"},
        "grade_to_grade_code": {str(v): k for k, v in CODE2GRADE.items()},
        "kasa": {"5": "ortaokul", "6": "ortaokul", "7": "ortaokul", "8": "ortaokul",
                 "9": "lise", "10": "lise", "11": "lise", "12": "lise"},
        "flow_endpoints": FLOWS,
        "flow_meaning": {"soru": "C kazanim + D sorular", "fasikul": "A konu ozetleri", "calisma": "B calisma defteri"},
        "url_templates": {
            "C_kazanim": BASE + "/soru-bankasi-kazanim/{slug}?s={gc}&d={d}&u=0&k=0",
            "D_test":    BASE + "/soru-bankasi/{slug}/test?s={gc}&d={d}&u=0&k={kazanim_ids}&id=&p=10&t=css&ks=0&os=0&zs=0",
            "A_list":    BASE + "/konu-ozetleri?s={gc}&d={d}&u=0&k=0",
            "B_list":    BASE + "/calisma-defteri-sec?s={gc}&d={d}&u=0&k=0",
        },
        "subjects": subjects,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # summary (ascii-safe)
    ns = sum(len(v) for v in subjects.values())
    print("wrote", OUT)
    print("grade codes:", list(subjects.keys()))
    for gc in GRADE_CODES:
        subs = subjects[str(gc)]
        g = CODE2GRADE.get(gc, "ozel")
        withslug = sum(1 for e in subs if e["slug"])
        print(f"  gc={gc} (grade {g}): {len(subs)} subjects, {withslug} with slug")
    print("total (grade x subject) rows:", ns)

if __name__ == "__main__":
    main()
