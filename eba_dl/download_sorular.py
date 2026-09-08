#!/usr/bin/env python3
"""D flow: EBA 'soru bankasi' questions -> question PNGs + answer key JSON.

Pipeline per (grade, subject) [uses the 'soru' flow]:
  1. read the vault kazanimlar.json (written by download_kazanim.py) -> kazanim_ids
  2. GET {BASE}/api/soru-tur-listele?id={kazanim_ids}  (batched)
        -> [{id(=soru id), cevap(=answer key), tip, srSoruKazanimlar, ...}]
           tip in css(coktan secmeli) / bbss / bds(bosluk) / bs / aus(acik uclu)
           cevap = answer index (1..5 => A..E for multiple-choice types)
  3. for each soru id: GET {BASE}/soru-bankasi/{slug}/test?...&id={soru_id}&t={tip}
        (render depends only on id; k=0 is fine) -> exactly ONE
        {BASE}/panel/upload/soru/{hash}.PNG  -> download.

Output:
  data/{kasa}/{grade}/{vault_slug}/sorular/{soru_id}.PNG
  data/{kasa}/{grade}/{vault_slug}/sorular.json
     [{"soru_id","tip","cevap","cevap_harf","image","kazanimlar"}]

ANSWER KEY: available (API 'cevap' field) -> written for every question.
Resumable, disk-guarded (<8GB), polite. Flags: --only-grade --only-slug --limit --force
"""
import os, re, json, time, argparse
import common as C

IMG_RE = re.compile(r"panel/upload/soru/([A-Za-z0-9_-]+\.png)", re.I)
HARF = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"}
MC_TIPS = {"css", "bbss", "bs"}  # multiple-choice-ish -> cevap maps to a letter


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def fetch_soru_records(s, kazanim_ids):
    recs = {}
    for grp in chunks(kazanim_ids, 40):
        ids = ",".join(str(x) for x in grp)
        r = C.get(s, f"{C.BASE}/api/soru-tur-listele?id={ids}")
        try:
            arr = r.json()
        except Exception:
            arr = []
        for d in arr:
            sid = d.get("id")
            if sid and sid not in recs:
                recs[sid] = {
                    "soru_id": sid,
                    "tip": d.get("tip"),
                    "cevap": d.get("cevap"),
                    "kazanimlar": d.get("srSoruKazanimlar") or [],
                }
        time.sleep(C.SLEEP)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-grade", type=int)
    ap.add_argument("--only-slug")
    ap.add_argument("--limit", type=int, help="max questions per subject (sampling)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    s = C.session()
    subj = imgs = skipped = noimg = 0
    for grade, kasa, gc, e in C.iter_subjects("soru", args.only_grade, args.only_slug):
        C.disk_guard()
        vslug, d, slug = e["vault_slug"], e["id"], e["slug"]
        kfp = C.vault_dir(kasa, grade, vslug, "kazanimlar.json")
        if not os.path.exists(kfp):
            print(f"-- grade {grade:>2} {vslug:<20} : no kazanimlar.json (run C first)"); continue
        kids = [row["kazanim_id"] for row in json.load(open(kfp, encoding="utf-8"))]
        if not kids:
            print(f"-- grade {grade:>2} {vslug:<20} : 0 kazanim"); continue
        recs = fetch_soru_records(s, kids)
        if not recs:
            print(f"-- grade {grade:>2} {vslug:<20} : 0 soru"); continue
        subj += 1
        outdir = C.vault_dir(kasa, grade, vslug, "sorular")
        os.makedirs(outdir, exist_ok=True)
        rows = []
        for i, (sid, rec) in enumerate(sorted(recs.items()), 1):
            if args.limit and i > args.limit:
                break
            tip = rec["tip"] or "css"
            turl = (f"{C.BASE}/soru-bankasi/{slug}/test?s={gc}&d={d}&u=0&k=0"
                    f"&id={sid}&p=1&t={tip}&ks=0&os=0&zs=0")
            image = None
            try:
                tr = C.get(s, turl)
                m = IMG_RE.search(tr.text)
                if m:
                    image = m.group(1)
            except Exception as ex:
                print(f"   ! test {grade} {vslug} soru {sid}: {ex}")
            cevap = rec["cevap"]
            harf = HARF.get(cevap) if (tip in MC_TIPS and isinstance(cevap, int)) else None
            row = {"soru_id": sid, "tip": tip, "cevap": cevap, "cevap_harf": harf,
                   "image": image, "kazanimlar": rec["kazanimlar"]}
            rows.append(row)
            if image:
                dest = os.path.join(outdir, f"{sid}.PNG")
                if args.force and os.path.exists(dest):
                    os.remove(dest)
                st, nb = C.download_binary(s, f"{C.BASE}/panel/upload/soru/{image}", dest, min_bytes=300)
                if st == 200:
                    imgs += 1
                elif st == "skip":
                    skipped += 1
                else:
                    print(f"   ! img {sid}: status {st}")
            else:
                noimg += 1
            time.sleep(C.SLEEP)
        json.dump(rows, open(C.vault_dir(kasa, grade, vslug, "sorular.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"OK grade {grade:>2} {vslug:<20} : {len(recs)} soru, {len(rows)} written (imgs+key)")
    print(f"\n==== D SUMMARY ==== subjects:{subj} imgs_new:{imgs} skipped:{skipped} no_image:{noimg} free:{C.free_gb():.1f}GB")


if __name__ == "__main__":
    main()
