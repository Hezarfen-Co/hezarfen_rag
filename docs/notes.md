# Notes.md — Kadir'in kontrolündeki dosya

> **Bu dosya Kadir'e aittir.** Ajanlar aşağıdaki Kadir bölümlerini
> DEĞİŞTİREMEZ / özetleyemez / silemez. Ajanlar yalnız **"Ajanın onay bekleyen
> önerileri"** bölümüne **tarihli** öneri ekler. Onaylanmayan öneri kesin karar sayılmaz.

## Kadir'in notları
_(Kadir doldurur)_

## Kadir'in aldığı kararlar
_(Kadir doldurur)_

## Düzeltilmesi gereken proje bilgileri
_(Kadir doldurur)_

## Açık sorular
_(Kadir doldurur)_

## Onaylanan öneriler
_(Kadir buraya taşır)_

---

## Ajanın onay bekleyen önerileri
> Ajan buraya tarihli öneri ekler; Kadir onaylarsa yukarı "Onaylanan öneriler"e taşır.

- **2026-08-31 — Dosya sistemi & çelişki temizliği (EXP-001 kapanışıyla gündeme geldi).** Geçen tur analizde tespit edilen düzeltmeler için onayın gerekiyor:
  1. `deney-sonuclari.md` + `README.md`: "kod yok / %0" bayat → güncel duruma çek.
  2. `deney-sonuclari.md`: golden set kaynağı `hezarfen_rag/mockdata/` → `data/` (mock düştü).
  3. Eşik çakışması: `benchmark.md` (KATI: faithfulness ≥0.99 vb.) ↔ `deney-sonuclari.md` (taslak ≥0.90). Öneri: `benchmark.md` tek doğruluk kaynağı, deney-sonuclari ona atıfla.
  4. Kırık wiki-linkler: `[[maliyet-ve-sunucu]]`, `[[test-tablolari]]` (dosya yok) → oluştur ya da linki kaldır.
  5. `Literatür/` → `reports/` altına taşınsın mı? (şu an çalışıyor; taşıma senin kararın.)
  > Bu maddeler **onayın olmadan uygulanmayacak** (kilitli dosyalar). Onaylarsan işleme alırım.
- **2026-08-31 — EXP-001 (korpus görsel/tablo analizi) inceleme bekliyor.** `reports/EXP-001-korpus-gorsel-tablo-analizi.md`. Bulgular kod+testle doğrulandı ama nihai kabul sende. Onaylarsan `COMPLETED.md`'ye taşınır.
- **2026-08-31 — Deney kapatma protokolü kaydedildi (kontrolünü bekliyor).** Standart "her deneyden sonra" 19-adım + değerlendirme paketi → `reports/DENEY-KAPATMA-PROTOKOLU.md`; AGENTS.md/CLAUDE.md ortak kural #8'e bağlandı (`shared_rules_version: 2`, iki dosya birebir eşleşiyor). Sen kontrol edip onaylarsan bağlayıcı standart olarak kalır; değişiklik istersen düzeltirim.
