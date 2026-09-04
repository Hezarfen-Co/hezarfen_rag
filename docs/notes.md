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
- **2026-09-01 — RES-001 derin literatür taraması kaydedildi + KİLİTLİ DOSYA DEĞİŞİKLİĞİ ÖNERİSİ.** `reports/RES-001-kaynakla-konusma-ozet-turkce-rag.md`. Bu tarama **mimari.md ve benchmark.md'yi etkiliyor** (ikisi de kilitli → onayın gerekiyor):
  1. **mimari.md:** BGE-M3 / bge-reranker-v2-m3 / DeepSeek-V4-Flash artık "kanıtlanmış varsayılan" değil **"Amber/aday"** olarak işaretlensin; **Türkçe baseline'lar eklensin** (multilingual-e5-large, TurkEmbed4Retrieval, Jina reranker); **claim–evidence sözleşmesi** + **çok-turlu durum çözümleyici** + **RAPTOR=yalnız routing (son cevap ham yaprak span)** + **extract-then-abstract varsayılanı** eklensin.
  2. **benchmark.md:** RES-001'deki **Hezarfen-RAG-TR-HN v1** tasarımı (1.200 soru, belge-bazlı split, hard-negative taksonomisi, answerable/partial/unanswerable, 5-boyut ayrı metrik, dilim-bazlı %95 GA + kritik hata üst sınırı kapıları) benimsensin; değişirse **yeni benchmark sürümü**.
  3. **plan.md:** yeni fazlar — gold set (TR-HN v1), bileşen benchmark'ı, oracle-context grounding, TR judge kalibrasyonu.
  4. **CONSTANTS.md:** kanıt-derecesi ölçeği (A/B/C/D) + model aday sınıflandırması sabitlensin.
  5. **Küçük:** `CLAUDE.md`/`AGENTS.md` başlığındaki "Bu klasör `C:/Users/w/Documents/Hezarfen/rag`" satırı artık kısmen bayat (yönetim dosyaları repo `docs/`'ta) — düzeltilsin mi?
  > Onaylarsan işleme alırım; onayın olmadan kilitli dosyaları değiştirmiyorum.
  - **DURUM 2026-09-02 — Kadir mimari kararını verdi ("başarılı RAG mimarisi, agentic/graph değil").** Madde 1 (mimari) UYGULANDI → `mimari.md §0.1 KESİN KARAR`: Uyarlamalı+Hibrit+Hiyerarşik; agentic/graph koşullu; RAPTOR-routing; extract-then-abstract; claim-evidence + fail-closed; BGE-M3/DeepSeek "aday". Madde 2 (benchmark eşik değerleri) ve 3 (plan fazları) golden set kurulunca netleşecek; 4 (CONSTANTS kanıt-derecesi) ve 5 (başlık düzeltme) küçük, sırada.
