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
- **2026-09-10 — EXP-009 (üretici LLM aday karşılaştırması) + yeni makine kurulumu; onayın bekleniyor.**
  Rapor: `reports/EXP-009-uretici-llm-karsilastirma.md` · ham veri + insan-okur soru/cevap
  defteri: `outputs/EXP-009-model-karsilastirma/`. Maliyet **$0** (NVIDIA ücretsiz uçlar;
  DeepSeek bakiyesine dokunulmadı). Onayına sunulan maddeler:
  1. **`nvidia/nemotron-3.5-lightning-30b-a3b` aday listesinden ÇIKARILSIN.** Gerekçe (ölçülü):
     nefret söylemi içeren 2 isteği "güvenli" saydı, intihar yöntemi sorusunda **bozuk JSON**
     döndürüp sınıflandırıcının fail-safe `allow` yoluna düştü, 1 jailbreak'i kaçırdı, kategori
     ve cevap metninde dil kirlenmesi var (`violence_凶手`, `促进하여`), kaynak yokken 8 item'ın
     7'sinde cevap uydurdu. Reşit-olmayan kitle için kabul edilemez.
  2. **Üretim modeli ŞİMDİ değişmesin.** EXP-009 retrieval'ı ölçmedi (oracle-bağlam vekili).
     `data/` geri yüklenince aynı 200-item golden set'le TAM boru hattı üzerinde her aday için
     `python -m src.eval.runner` koşulup karar verilsin. Aday sırası (şimdilik):
     `nvidia/nemotron-3-super-120b-a12b` (p50 1,94 s) ≈ `meta/muse-glimmer-30b` (çekimserlik 8/8).
  3. **`_looks_like_abstain` parafraz toleransı** (küçük, davranış değiştirmez): modeller
     "Kaynaklarda **kemosentez hakkında** bilgi bulunamadı." diye parafraz ediyor; üretim bunu
     `model_abstained` değil `ungrounded_no_citations` olarak etiketliyor (güvenlik AÇIĞI YOK,
     ürün zaten çekimser dönüyor) ama değerlendirmede iki kök neden karışıyor. Onaylarsan
     `reason` ayrımını koruyarak parafraz toleransı eklenir.
  4. **Obsidian `rag/` bayat belgeleri güncellendi** (senin izninle, 2026-09-10):
     `README.md` ("kod yok %0" → gerçek durum), `deney-sonuclari.md` (§4 LLM tablosu dolduruldu
     + bayat başlık), `gorevler.md` (S1-S8 ve özellik durumları). `plan.md`'ye **kutucuklarına
     dokunmadan** tarihli bir güncelleme bloğu eklendi. **Kilitli dosyalara (`mimari.md`,
     `benchmark.md`, `bulgular.md`, `Notes.md`) ve `Hezarfen/chatbot/` klasörüne DOKUNULMADI.**
  5. **Bu makinenin engelleri (senin aksiyonun gerekiyor):** `gh` CLI kurulu değil ama git
     credential helper ona bakıyor → **4 deponun hiçbiri fetch/pull/push edemiyor**;
     `sudo dnf install gh && gh auth login` sonrası `git lfs pull` (15,6 GB) ile `data/` gelir.
     Ayrıca NVIDIA sürücüsü yok (embed/rerank CPU'da, BGE-M3 ~4,1 chunk/s) ve `tesseract` yok
     (OCR yolu sınanamaz). `.env` anahtar adları ASCII'ye çevrildi — eskiden kod hiçbirini
     okuyamıyordu (`DEEP_SEEK_API_KEY `, `NVİDİA_APİ_KEY`).
  6. **`moonshotai/kimi-k3` ölçülemedi:** bu makinede aynı NVIDIA anahtarını kullanan ikinci bir
     oturum (MedExam-AiServices) kotayı tutuyor; tek çağrı bile anında `429`. O oturum kapanınca
     tek başına yeniden koşulmalı (koşum arka planda bırakıldı).
- **2026-09-11 — EXP-010 denetimi + ürün kriterleri; onayın bekleniyor.**
  Yeni md dosyası üretmemek için her şey MEVCUT yapıya yazıldı: bulgular
  `reports/EXP-010-urun-hazirlik-denetimi.md` (+ §7 issue taslakları), ürün kriterleri
  Obsidian `rag/benchmark.md §8` (senin "iki kademe" kararınla; **§3'ün katı kapıları
  değiştirilmedi**, onlar artık "Tam Ürün" kademesi), literatür geliştirmeleri
  `OPTIMIZATION.md §I`, devralma `Backlog.md` BL-007.
  **Onayına sunulan kararlar:** (a) `benchmark.md §8` iki-kademeli kapılar,
  (b) kriz hattı numarası, (c) prompt "birden çok kaynağı atıfla" ↔ metrik "fazla atıfı
  cezalandır" çelişkisinin çözümü (metrik değişirse `benchmark.md` kilidi gereği YENİ
  sürüm açılır), (d) golden set v2 (şekil/tablo, global/özet, adversarial, hard-negative,
  alan-içi-cevapsız item'lar) onayı, (e) NVIDIA sürücüsü kurulsun mu.
  **Commit imzası:** senin 2026-09-11 kararınla ortak kural 15 aynen uygulanıyor —
  yazar Kadir, commit'lerde AI izi yok (bu, oturum talimatımdaki `Co-Authored-By`
  satırını devre dışı bırakıyor).
