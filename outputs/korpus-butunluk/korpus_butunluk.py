"""Korpus butunlugu: kitap metni ile kazanimlar.json ayni mufredattan mi?

Olcut: her kazanimin UNITE adindaki anlamli sozcukler kitap metninde geciyor mu.
Gecmiyorsa o unite kitapta YOK demektir -- kazanim dosyasi baska bir mufredat
surumunden gelmis olur ve uzerine kurulan her olcum (golden set, konu kapsami,
kisisellestirme) sessizce yanlis olur.
"""
import json, os, re, sys, unicodedata
sys.path.insert(0, ".")
import pymupdf

def katla(s):
    s = s.replace("İ","i").replace("I","ı").replace("ı","i").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))

DUR = {"ve","ile","bir","bu","icin","genel","ilkeleri","islemler","sistemleri",
       "sistemi","cesitleri","yapisi","olaylari","dunyasi"}
kok = "data/lise/10"
sonuc = []
for ders in sorted(os.listdir(kok)):
    kj = os.path.join(kok, ders, "kazanimlar.json")
    pdf = os.path.join(kok, ders, "kitap.pdf")
    if not (os.path.isfile(kj) and os.path.isfile(pdf)):
        continue
    kz = json.load(open(kj, encoding="utf-8"))
    uniteler = []
    for k in kz:
        u = k.get("unite")
        if u and u not in uniteler:
            uniteler.append(u)
    d = pymupdf.open(pdf)
    metin = katla("\n".join(d[i].get_text() for i in range(d.page_count)))
    d.close()
    bulunan = 0
    eksikler = []
    for u in uniteler:
        kelimeler = [w for w in re.findall(r"[a-z]{4,}", katla(u)) if w not in DUR]
        if not kelimeler:
            continue
        varlik = sum(1 for w in kelimeler if w in metin) / len(kelimeler)
        if varlik >= 0.5:
            bulunan += 1
        else:
            eksikler.append(u)
    sonuc.append({"ders": ders, "unite": len(uniteler), "kitapta_var": bulunan,
                  "oran": round(bulunan / max(1, len(uniteler)), 2),
                  "eksik": eksikler[:4], "sayfa": len(metin)})
    e = f" | EKSIK: {', '.join(eksikler[:3])}" if eksikler else ""
    print(f"{ders:16} unite={len(uniteler):2} kitapta={bulunan:2} "
          f"oran={bulunan/max(1,len(uniteler)):.2f}{e}")
json.dump(sonuc, open(sys.argv[1], "w"), ensure_ascii=False, indent=2)
