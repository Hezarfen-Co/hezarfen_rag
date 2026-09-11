"""Gösterim/örnek veri üretimi — ÜRÜN KODU DEĞİL.

Buradaki her şey backend'in gerçek kayıt biçiminde **örnek** veri üretir:
bir okul, şubeler, öğrenciler, ders kayıtları, notlar. İki işe yarar:
tohumlama (ayakta bir backend'e POST edilebilir) ve çevrimdışı koşum
(`src/bridge` gerçek bir bağlantı olmadan uçtan uca denenebilir).

`src/bridge`'den ayrı tutulur: orası üretimde koşan entegrasyon kodu,
burası onu beslemek için üretilen veridir. İkisi karışırsa "hangi kod
üretimde çalışıyor" sorusu cevapsız kalır.
"""
from .scenario import Scenario, build_scenario
from .school import School, FakeSchool, build_school

__all__ = ["Scenario", "build_scenario", "School", "FakeSchool", "build_school"]
