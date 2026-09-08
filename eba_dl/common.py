#!/usr/bin/env python3
"""Shared helpers for EBA (ogmmateryal.eba.gov.tr) downloaders.

Site facts (see build_codes.py / eba_codes.json):
  * OGM = high school only, grades 9-12.
  * grade query code = grade - 3  (6->9, 7->10, 8->11, 9->12); code 4 = special Matematik.
  * subject 'd' code is per-grade; slug = urlKod (matematik, biyoloji, ...).
Vault: data/{kasa}/{grade}/{vault_slug}/...
"""
import os, json, time, shutil, sys
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = r"C:/Users/w/Desktop/Kodlama/VsCode/HelloWorld/Hezarfen/hezarfen_rag/data"
CODES = json.load(open(os.path.join(HERE, "eba_codes.json"), encoding="utf-8"))
BASE = CODES["base"]                      # https://ogmmateryal.eba.gov.tr
CDN = CODES["cdn"]                         # https://ogm-large-cdn.eba.gov.tr
CODE2GRADE = {6: 9, 7: 10, 8: 11, 9: 12}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MIN_FREE_GB = 8.0                          # stop if free disk < this
SLEEP = 0.4                               # politeness delay between requests


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def free_gb(path=VAULT):
    p = path
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    return shutil.disk_usage(p or "C:/").free / (1024 ** 3)


def disk_guard():
    fg = free_gb()
    if fg < MIN_FREE_GB:
        print(f"!! DISK GUARD: only {fg:.1f} GB free (< {MIN_FREE_GB} GB). Stopping.")
        sys.exit(2)
    return fg


def iter_subjects(flow, only_grade=None, only_slug=None):
    """Yield (grade, kasa, gc, subject_dict) for subjects available in `flow`
    ('soru' | 'fasikul' | 'calisma'), grades 9-12 only (skips special gc=4)."""
    for gc_str, subs in CODES["subjects"].items():
        gc = int(gc_str)
        if gc not in CODE2GRADE:
            continue
        grade = CODE2GRADE[gc]
        if only_grade and grade != only_grade:
            continue
        kasa = CODES["kasa"][str(grade)]
        for e in subs:
            if flow not in e["flows"]:
                continue
            if not e.get("slug"):
                continue
            if only_slug and e["vault_slug"] != only_slug:
                continue
            yield grade, kasa, gc, e


def vault_dir(kasa, grade, vslug, *sub):
    d = os.path.join(VAULT, kasa, str(grade), vslug, *sub)
    return d


def get(s, url, tries=3, timeout=30, **kw):
    last = None
    for _ in range(tries):
        try:
            r = s.get(url, timeout=timeout, **kw)
            return r
        except Exception as ex:
            last = ex
            time.sleep(1.0)
    raise last


def download_binary(s, url, dest, min_bytes=200):
    """Download url->dest. Returns (status, bytes). Skips existing non-trivial files."""
    if os.path.exists(dest) and os.path.getsize(dest) >= min_bytes:
        return ("skip", os.path.getsize(dest))
    r = get(s, url, stream=True)
    if r.status_code != 200:
        return (r.status_code, 0)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    n = 0
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(65536):
            if chunk:
                f.write(chunk); n += len(chunk)
    if n < min_bytes:
        os.remove(tmp)
        return ("tiny", n)
    os.replace(tmp, dest)
    return (200, n)
