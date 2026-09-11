"""Uçtan uca öğrenci koşumu: backend kimliği → kasa izolasyonu → atıflı cevap.

Bu bir DEMO değil, bir DOĞRULAMADIR: senaryodaki öğrencinin kendi notundaki
kazanım metninden soru üretir ve ürünün tam yolunu koşturur. Çıktı
`outputs/ogrenci-senaryosu/` altına yazılır ki insan incelemesi yapılabilsin.

Koşum: .venv/bin/python -m src.bridge.demo_ogrenci [ders] [soru]
"""
from __future__ import annotations

import json
import os
import sys
import time

from ..guard.roles import Role, RoleContext, can_access
from ..bridge.client import FakeReader
from ..bridge.student import build_context
from .scenario import build_scenario, write

SENARYO = "outputs/ogrenci-senaryosu/lise-10-ogrenci1.json"
CIKTI = "outputs/ogrenci-senaryosu/kosum-lise-10.json"


def _pipeline(sinif: str, ders: str):
    from ..service.http_app import build_service
    kitap = os.path.join("data", "lise", sinif, ders, "kitap.pdf")
    if not os.path.isfile(kitap):
        raise SystemExit(f"kitap yok: {kitap}")
    return build_service(kitap, sinif=sinif, ders=ders)


def main() -> None:
    ders = sys.argv[1] if len(sys.argv) > 1 else "biyoloji"

    senaryo = build_scenario()
    write(senaryo, SENARYO)
    baglam = build_context(FakeReader.from_snapshot(SENARYO), senaryo.ogrenci["id"])
    print(f"[ogrenci] {baglam.ad} ({baglam.rol}) · {baglam.sube} · sinif "
          f"{baglam.sinif} · {len(baglam.dersler)} ders · {len(baglam.notlar)} not")

    # Soru, öğrencinin KENDİ notundan gelir — uydurma bir soru değil.
    #
    # KOŞARAK ÖĞRENİLDİ: kazanım metnini ("Canlılarda hücre bölünmesinin
    # gerekliliğini açıklar.") kaba bir kuralla soruya çevirmek bozuk bir cümle
    # üretiyordu ("... açıklar nedir?") ve kanıt kapısı haklı olarak
    # `insufficient_data` ile reddediyordu. Türkçe çekim eklerini kuralla
    # sökmek güvenilmez; kazanım metnini AYNEN taşıyıp etrafına doğal bir
    # yönerge sarmak hem dilbilgisel hem sadık.
    kendi_not = next((n for n in baglam.notlar if ders.split("-")[-1][:3].lower()
                      in n.title.lower()), baglam.notlar[0] if baglam.notlar else None)
    if len(sys.argv) > 2:
        soru = sys.argv[2]
    elif kendi_not:
        kazanim = kendi_not.content.splitlines()[0].split(" ", 1)[1].rstrip(".")
        soru = f"{kazanim.capitalize()} — bunu kaynaklara dayanarak açıklar mısın?"
    else:
        soru = "Mitoz nedir?"
    print(f"[soru] {soru}\n[not ] {kendi_not.title if kendi_not else '-'}")

    t0 = time.time()
    servis = _pipeline(baglam.sinif, ders)
    print(f"[kurulum] {time.time() - t0:.1f}s")

    rol = baglam.role_context()
    kayit = {"ogrenci": {"ad": baglam.ad, "rol": baglam.rol, "sinif": baglam.sinif,
                         "sube": baglam.sube, "ders_sayisi": len(baglam.dersler)},
             "soru": soru, "kaynak_not": kendi_not.title if kendi_not else None,
             "senaryolar": []}

    for etiket, ctx, hedef_ders in (
            ("kendi dersi (IZIN bekleniyor)", rol, ders),
            ("kayitli olmadigi ders (RED bekleniyor)", rol, "astronomi"),
            ("baska sinif (RED bekleniyor)",
             RoleContext(role=Role.STUDENT, sinif="11", ders_list=baglam.dersler), ders),
            ("rol yok (RED bekleniyor)", None, ders)):
        izin = can_access(ctx, sinif=baglam.sinif, ders=hedef_ders)
        satir = {"senaryo": etiket, "hedef_ders": hedef_ders, "izin": izin}
        if izin:
            t1 = time.time()
            cevap = servis.chat({"query": soru,
                                 "role": {"role": ctx.role.value, "sinif": ctx.sinif,
                                          "ders_list": ctx.ders_list},
                                 "options": {"top_n": 6, "candidate_n": 40}})
            satir.update({"sure_s": round(time.time() - t1, 2),
                          "abstained": cevap.get("abstained"),
                          "reason": cevap.get("reason"),
                          "metin": cevap.get("text"),
                          "atiflar": cevap.get("citations"),
                          "gecersiz_atiflar": cevap.get("invalid_citations"),
                          "maliyet_usd": cevap.get("cost_usd")})
        kayit["senaryolar"].append(satir)
        print(f"  - {etiket:40} izin={izin}"
              + (f" abstained={satir.get('abstained')} "
                 f"atif={len(satir.get('atiflar') or [])}" if izin else ""))

    os.makedirs(os.path.dirname(CIKTI), exist_ok=True)
    with open(CIKTI, "w", encoding="utf-8") as fh:
        json.dump(kayit, fh, ensure_ascii=False, indent=2)
    print(f"\n[yazildi] {CIKTI}")
    for s in kayit["senaryolar"]:
        if s.get("metin"):
            print(f"\n--- CEVAP ---\n{s['metin']}\n--- ATIFLAR ---")
            for c in s.get("atiflar") or []:
                print(f"  [{c['n']}] s.{c['pages']} {c['ders']}")


if __name__ == "__main__":
    main()
