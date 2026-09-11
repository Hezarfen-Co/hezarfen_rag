"""Kazanim duzeyinde kapsam: kitap bu kazanimi CEVAPLAYABILIR mi?

Olcut: kazanim metnindeki ayirt edici (>=5 harf, durak-disi) sozcuklerin kacta
kaci kitap metninde geciyor. >=0.5 ise 'kapsanmis' sayilir. Bu kaba bir vekildir
ama YONU dogru verir: 0'a yakin bir kazanim kitapta kesinlikle yok.
"""
import json, os, re, sys, unicodedata
sys.path.insert(0, ".")
import pymupdf

def katla(s):
    s = s.replace("İ","i").replace("I","ı").replace("ı","i").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))

DUR = {"aciklar","ornekle","orneklerle","analiz","eder","edilir","yapar","kavrar",
       "yorumlar","degerlendirir","iliskilendirir","siniflandirir","tartisir",
       "canlilarda","genel","esaslarini","ozelliklerini","onemini","uzerinde",
       "arasindaki","iliskiyi","cikarimlarda","bulunur","olusturur","kullanarak"}
kok = "data/lise/10"
rapor = []
for ders in sorted(os.listdir(kok)):
    kj, pdf = os.path.join(kok, ders, "kazanimlar.json"), os.path.join(kok, ders, "kitap.pdf")
    if not (os.path.isfile(kj) and os.path.isfile(pdf)):
        continue
    kz = json.load(open(kj, encoding="utf-8"))
    d = pymupdf.open(pdf); metin = katla("\n".join(d[i].get_text() for i in range(d.page_count))); d.close()
    kapsanan, eksik = 0, []
    for k in kz:
        kelimeler = [w for w in re.findall(r"[a-z]{5,}", katla(k.get("metin",""))) if w not in DUR]
        if not kelimeler:
            kapsanan += 1; continue
        oran = sum(1 for w in kelimeler if w in metin) / len(kelimeler)
        if oran >= 0.5:
            kapsanan += 1
        else:
            eksik.append(f"{k['kod']} {k['metin'][:52]}")
    rapor.append({"ders": ders, "kazanim": len(kz), "kapsanan": kapsanan,
                  "oran": round(kapsanan/max(1,len(kz)), 3), "eksik_ornek": eksik[:5],
                  "eksik_sayi": len(eksik)})
    print(f"{ders:14} kazanim={len(kz):3} kapsanan={kapsanan:3} oran={kapsanan/max(1,len(kz)):.2f}"
          f"  eksik={len(eksik)}")
    for e in eksik[:3]:
        print(f"                 ! {e}")
json.dump(rapor, open(sys.argv[1],"w"), ensure_ascii=False, indent=2)
