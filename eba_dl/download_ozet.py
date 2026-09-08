#!/usr/bin/env python3
"""A flow: EBA 'konu ozetleri' (topic summaries).

DISCOVERY NOTE: A is NOT a CDN flipbook (that was B). Konu ozeti items are
individual PDFs served from the MAIN domain:
    list page : {BASE}/konu-ozetleri?s={gc}&d={d}&u=0&k=0   (SSR HTML)
    each item : onclick="pdfGoster('{hash}.pdf', this)"
    pdf url   : {BASE}/panel/upload/fasikul/{hash}.pdf       (application/pdf)

Output (deviates from assumed {N}.jpg because source is PDF):
    data/{kasa}/{grade}/{vault_slug}/konu-ozeti/{NN}_{hash}.pdf
    data/{kasa}/{grade}/{vault_slug}/konu-ozeti/index.json  [{sira,baslik,dosya,url}]

Resumable (skips existing), disk-guarded (<8GB free stops), polite (UA + delay).
Usage:
  python download_ozet.py                 # ALL grades 9-12 x A-subjects  (bulk -> run by user)
  python download_ozet.py --only-grade 11 --only-slug matematik --limit 2   # sample test
"""
import os, re, json, time, html, argparse
import common as C

ITEM_RE = re.compile(r"<a\b[^>]*onclick=\"pdfGoster\('([^']+\.pdf)'[^>]*>(.*?)</a>", re.S | re.I)


def parse_items(page):
    out = []
    for m in ITEM_RE.finditer(page):
        fn = m.group(1).strip()
        title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
        title = re.sub(r"\s+", " ", title).strip().lstrip("→ ").strip()
        out.append((fn, title))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-grade", type=int)
    ap.add_argument("--only-slug")
    ap.add_argument("--limit", type=int, help="max PDFs per subject (sampling)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    s = C.session()
    subj = pdfs = skipped = 0
    for grade, kasa, gc, e in C.iter_subjects("fasikul", args.only_grade, args.only_slug):
        C.disk_guard()
        vslug, d = e["vault_slug"], e["id"]
        url = f"{C.BASE}/konu-ozetleri?s={gc}&d={d}&u=0&k=0"
        try:
            r = C.get(s, url)
        except Exception as ex:
            print(f"ERR list {grade} {vslug}: {ex}"); continue
        items = parse_items(r.text)
        if not items:
            print(f"-- grade {grade:>2} {vslug:<20} : 0 items"); time.sleep(C.SLEEP); continue
        outdir = C.vault_dir(kasa, grade, vslug, "konu-ozeti")
        os.makedirs(outdir, exist_ok=True)
        idx = []
        subj += 1
        for i, (fn, title) in enumerate(items, 1):
            if args.limit and i > args.limit:
                break
            dest = os.path.join(outdir, f"{i:02d}_{fn}")
            purl = f"{C.BASE}/panel/upload/fasikul/{fn}"
            if args.force and os.path.exists(dest):
                os.remove(dest)
            st, nb = C.download_binary(s, purl, dest, min_bytes=500)
            idx.append({"sira": i, "baslik": title, "dosya": os.path.basename(dest), "url": purl})
            if st == 200:
                pdfs += 1
            elif st == "skip":
                skipped += 1
            else:
                print(f"   ! {grade} {vslug} {fn}: status {st}")
            time.sleep(C.SLEEP)
        json.dump(idx, open(os.path.join(outdir, "index.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"OK grade {grade:>2} {vslug:<20} : {len(items)} items (idx written)")
    print(f"\n==== A SUMMARY ==== subjects:{subj} pdfs_new:{pdfs} skipped:{skipped} free:{C.free_gb():.1f}GB")


if __name__ == "__main__":
    main()
