#!/usr/bin/env python3
"""B flow: EBA 'calisma defteri' (workbook) -> CDN flipbook JPGs.

    select page : {BASE}/calisma-defteri-sec?s={gc}&d={d}&u=0&k=0
                  (302 -> /calisma-defteri/{slug}?s=..&d=..)  SSR HTML lists fasikuls
    each fasikul thumb in HTML:
        {CDN}/ogm-materyal/calisma_defteri/f{F}/{grade}/{slug}/files/thumb/1.jpg
    pages:
        {CDN}/ogm-materyal/calisma_defteri/f{F}/{grade}/{slug}/files/mobile/{N}.jpg
        N = 1,2,...  count up until HTTP 403 (CDN returns 403 past the last page).

CDN paths are PARSED from the page (grade + slug taken from the thumb URL), so no
guessing of the in-path subject name.

Output: data/{kasa}/{grade}/{vault_slug}/calisma-defteri/f{F}/{N}.jpg
Resumable, disk-guarded (<8GB), polite. Usage same flags as download_ozet.py.
"""
import os, re, json, time, argparse
import common as C

THUMB_RE = re.compile(
    r"ogm-materyal/calisma_defteri/f(\d+)/(\d+)/([a-z0-9_-]+)/files/thumb/1\.jpg", re.I)


def parse_fasikuls(page):
    """-> list of (fasikul_no, grade_in_path, slug_in_path) unique, ordered."""
    seen, out = set(), []
    for m in THUMB_RE.finditer(page):
        key = (m.group(1), m.group(2), m.group(3))
        if key not in seen:
            seen.add(key); out.append((int(m.group(1)), m.group(2), m.group(3)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-grade", type=int)
    ap.add_argument("--only-slug")
    ap.add_argument("--limit", type=int, help="max pages per fasikul (sampling)")
    ap.add_argument("--max-miss", type=int, default=2, help="consecutive 403/404 before stopping a fasikul")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    s = C.session()
    subj = pages = skipped = 0
    for grade, kasa, gc, e in C.iter_subjects("calisma", args.only_grade, args.only_slug):
        C.disk_guard()
        vslug, d, slug = e["vault_slug"], e["id"], e["slug"]
        url = f"{C.BASE}/calisma-defteri-sec?s={gc}&d={d}&u=0&k=0"
        try:
            r = C.get(s, url)      # follows 302 to /calisma-defteri/{slug}
        except Exception as ex:
            print(f"ERR list {grade} {vslug}: {ex}"); continue
        fas = parse_fasikuls(r.text)
        if not fas:
            print(f"-- grade {grade:>2} {vslug:<20} : 0 fasikul"); time.sleep(C.SLEEP); continue
        subj += 1
        print(f"grade {grade:>2} {vslug:<20} : {len(fas)} fasikul {[f[0] for f in fas]}")
        for fno, gpath, spath in fas:
            outdir = C.vault_dir(kasa, grade, vslug, "calisma-defteri", f"f{fno}")
            base = f"{C.CDN}/ogm-materyal/calisma_defteri/f{fno}/{gpath}/{spath}/files/mobile"
            n = 0
            miss = 0
            while True:
                n += 1
                if args.limit and n > args.limit:
                    break
                dest = os.path.join(outdir, f"{n}.jpg")
                if args.force and os.path.exists(dest):
                    os.remove(dest)
                st, nb = C.download_binary(s, f"{base}/{n}.jpg", dest, min_bytes=500)
                if st == 200:
                    pages += 1; miss = 0
                elif st == "skip":
                    skipped += 1; miss = 0
                else:
                    miss += 1
                    if miss >= args.max_miss:
                        n -= miss
                        break
                time.sleep(C.SLEEP)
            print(f"   f{fno}: ~{max(n,0)} pages")
    print(f"\n==== B SUMMARY ==== subjects:{subj} pages_new:{pages} skipped:{skipped} free:{C.free_gb():.1f}GB")


if __name__ == "__main__":
    main()
