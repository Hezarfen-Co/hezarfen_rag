#!/usr/bin/env python3
"""EXP-009 ham çıktılarını insan-okur soru/cevap defterine çevirir (Kadir incelemesi).

Kural 9 (insan denetimi): otomatik metrik tek başına yeterli değil; Kadir'in
GERÇEK cevapları okuyabilmesi gerekiyor. Bu betik her modelin her item'daki ham
cevabını, beklenen davranışı ve otomatik kararı yan yana yazar.
"""
import glob
import json
import os
import sys

BASE = sys.argv[1]
OUT = os.path.join(BASE, "soru-cevap-defteri.md")

by_model = {}
for f in sorted(glob.glob(os.path.join(BASE, "*", "raw", "*.jsonl"))):
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        by_model.setdefault(r["model"], []).append(r)

L = ["# EXP-009 — Soru/Cevap defteri (insan incelemesi için)",
     "",
     "> Otomatik kararlar YALNIZ yardımcıdır (ortak kural 9). Nihai kabul Kadir'de.",
     "> `beklenen` = golden set etiketi · `karar` = harness'ın deterministik skoru.",
     ""]

for model, recs in sorted(by_model.items()):
    L += [f"## {model}", ""]
    for task, title in [("T1_guard", "T1 — Güvenlik sınıflandırıcı"),
                        ("T2_rewrite", "T2 — Çok-turlu bağımsız sorgu"),
                        ("T3_grounded", "T3 — Kaynak-sınırlı cevap + atıf")]:
        sub = [r for r in recs if r["task"] == task]
        if not sub:
            continue
        L += [f"### {title} ({len(sub)} item)", ""]
        for r in sub:
            if r.get("err"):
                L += [f"- **{r.get('id')}** — ÇAĞRI HATASI: `{r['err'][:120]}`", ""]
                continue
            if task == "T1_guard":
                mark = "✅" if r["ok"] else "❌"
                L += [f"- {mark} **{r['id']}** ({r['tur']}) — beklenen `{r['beklenen']}`"
                      f"/`{r['beklenen_kategori']}`, karar "
                      f"`{r['verdict']['action']}`/`{r['verdict']['category']}`",
                      f"  - soru: {r['soru']}",
                      f"  - ham JSON: `{(r['raw'] or '').strip()[:300]}`", ""]
            elif task == "T2_rewrite":
                L += [f"- **{r['id']}** — token-F1 {r['f1']:.2f}",
                      f"  - takip sorusu: {r['soru']}",
                      f"  - beklenen bağımsız: {r['beklenen']}",
                      f"  - modelin ürettiği: {r['pred']}", ""]
            else:
                mark = "✅" if r["ok"] else "❌"
                L += [f"- {mark} **{r['id']}** ({r['tur']}) — doğru kaynak "
                      f"`[{r['dogru_n']}]`, model atıfları `{r['citations']}`, "
                      f"çekimser={r['abstained']}, gold-F1 {r['gold_f1']:.2f}"
                      + (", ⚠️ JAILBREAK" if r.get("jailbroken") else ""),
                      f"  - soru: {r['soru']}",
                      f"  - cevap: {(r['cevap'] or '(boş)').strip()[:700]}", ""]

open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("yazıldı:", OUT, os.path.getsize(OUT), "bayt")
