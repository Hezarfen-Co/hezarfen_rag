#!/usr/bin/env python3
"""C flow: download EBA 'kazanim' (learning outcome) lists -> vault kazanimlar.json

Source page (SSR HTML):
  https://ogmmateryal.eba.gov.tr/soru-bankasi-kazanim/{slug}?s={gc}&d={d}&u=0&k=0
Structure:
  <li class="units-Select-item">
    <input id="cbUnite-{unite_id}" ...><span class="fw-bold">Unite adi</span>
    <ul class="units-Select-item-details">
      <li><input id="cbKazanim-{kazanim_id}" value="{kazanim_id}"> {kod}.- {metin}</li>
      ...
Output: data/{kasa}/{grade}/{vault_slug}/kazanimlar.json
  [{"unite_id":..,"unite":..,"kazanim_id":..,"kod":..,"metin":..}]

Reads eba_codes.json. Resumable (skips existing non-empty files unless --force).
"""
import os, re, json, time, html, argparse, sys
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CODES = json.load(open(os.path.join(HERE, "eba_codes.json"), encoding="utf-8"))
VAULT = r"C:/Users/w/Desktop/Kodlama/VsCode/HelloWorld/Hezarfen/hezarfen_rag/data"
BASE = CODES["base"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CODE2GRADE = {6: 9, 7: 10, 8: 11, 9: 12}

UNIT_RE = re.compile(
    r'<li class="units-Select-item">(.*?)</li>\s*</ul>\s*</li>', re.S)
# Simpler: split on each unit item start.
UNIT_SPLIT = re.compile(r'<li class="units-Select-item">')
UNITE_ID_RE = re.compile(r'cbUnite-(\d+)')
UNITE_NAME_RE = re.compile(r'<span class="fw-bold">\s*(.*?)\s*</span>', re.S)
KAZ_ITEM_RE = re.compile(
    r'<input[^>]*id="cbKazanim-(\d+)"[^>]*value="(\d+)"[^>]*>\s*(.*?)\s*</label>', re.S)


def parse_kazanimlar(page):
    rows = []
    parts = UNIT_SPLIT.split(page)
    for chunk in parts[1:]:
        # cut chunk at the start of the next unit's parent list end to be safe: use whole chunk
        mid = UNITE_ID_RE.search(chunk)
        mname = UNITE_NAME_RE.search(chunk)
        unite_id = int(mid.group(1)) if mid else None
        unite = html.unescape(re.sub(r'\s+', ' ', mname.group(1))).strip() if mname else None
        # only take the details block for this unit (up to first </ul>)
        det = chunk.split('units-Select-item-details', 1)
        detail_html = det[1] if len(det) > 1 else chunk
        detail_html = detail_html.split('</ul>', 1)[0]
        for km in KAZ_ITEM_RE.finditer(detail_html):
            kid = int(km.group(2))
            raw = html.unescape(re.sub(r'\s+', ' ', km.group(3))).strip()
            m = re.match(r'^(.+?)\.-\s*(.+)$', raw)
            if m:
                kod, metin = m.group(1).strip(), m.group(2).strip()
            else:
                kod, metin = None, raw
            rows.append({"unite_id": unite_id, "unite": unite,
                         "kazanim_id": kid, "kod": kod, "metin": metin})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="overwrite existing non-empty files")
    ap.add_argument("--only-slug", help="restrict to one vault_slug (test)")
    ap.add_argument("--only-grade", type=int, help="restrict to one display grade (test)")
    args = ap.parse_args()

    s = requests.Session()
    s.headers.update({"User-Agent": UA})

    written = 0
    empty = []
    skipped = 0
    errors = []
    for gc_str, subs in CODES["subjects"].items():
        gc = int(gc_str)
        if gc not in CODE2GRADE:
            continue  # skip special gc=4
        grade = CODE2GRADE[gc]
        if args.only_grade and grade != args.only_grade:
            continue
        kasa = CODES["kasa"][str(grade)]
        for e in subs:
            if "soru" not in e["flows"]:
                continue  # C lives in the soru flow
            slug, vslug, d = e["slug"], e["vault_slug"], e["id"]
            if not slug:
                errors.append((grade, e["baslik"], "no-slug"))
                continue
            if args.only_slug and vslug != args.only_slug:
                continue
            outdir = os.path.join(VAULT, kasa, str(grade), vslug)
            outfp = os.path.join(outdir, "kazanimlar.json")
            if (not args.force) and os.path.exists(outfp) and os.path.getsize(outfp) > 2:
                skipped += 1
                continue
            url = f"{BASE}/soru-bankasi-kazanim/{slug}?s={gc}&d={d}&u=0&k=0"
            try:
                r = s.get(url, timeout=30)
                if r.status_code != 200:
                    errors.append((grade, vslug, f"HTTP {r.status_code}"))
                    time.sleep(0.4); continue
                rows = parse_kazanimlar(r.text)
            except Exception as ex:
                errors.append((grade, vslug, f"ERR {ex}"))
                time.sleep(0.4); continue
            os.makedirs(outdir, exist_ok=True)
            json.dump(rows, open(outfp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            if rows:
                written += 1
                print(f"OK  grade {grade:>2} {vslug:<22} d={d:<3} -> {len(rows)} kazanim")
            else:
                empty.append((grade, vslug, d))
                print(f"EMPTY grade {grade:>2} {vslug:<22} d={d}")
            time.sleep(0.4)

    print("\n==== SUMMARY ====")
    print("written(non-empty):", written, " empty:", len(empty), " skipped:", skipped, " errors:", len(errors))
    if empty:
        print("EMPTY:", empty)
    if errors:
        print("ERRORS:", errors)


if __name__ == "__main__":
    main()
