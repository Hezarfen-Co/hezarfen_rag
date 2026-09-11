# Backlog.md — Başlanan / yarım kalan işler (devralma bağlamıyla)

> Kural: iş bitince **Kadir onayı** ile buradan çıkarılıp `COMPLETED.md`'ye taşınır.
> Her madde: ne yapıldı · kaldığı yer · sonraki kesin adım · ilgili dosyalar.

## Açık (devam eden)

### BL-001 — Faz 0 tamamlanması (ingest hijyeni)
- **Yapıldı:** 0.3a/b/c/d ✅, 0.4 (izolasyon) ✅, 0.6 (TR normalize) ✅, 0.7 (curriculum graph) ✅ (kod deposu HEAD `4924a2a`).
- **Kalan:** **0.5** (kanonik doküman şeması + metadata — parse+izole+görsel+tablo+kazanım'ı tek chunk'lanabilir dokümanda birleştir) · **0.8** (konu-özeti PDF + çalışma-defteri JPG OCR).
- **Sonraki kesin adım:** 0.5 kanonik şema (Faz 1'e köprü).
- **İlgili:** `plan.md` Faz 0 · `hezarfen_rag/src/ingest/`.

### BL-002 — Faz 1: Text-RAG baseline (kaynakla konuşma) — HENÜZ BAŞLAMADI
- **Bağlam:** ilk **model deneyi** (EXP-002) burada olacak; DeepSeek-flash + BGE-M3 + Qdrant + BM25 + reranker → golden set + DeepEval.
- **Ön koşul:** BL-001 (0.5) + golden set (benchmark.md §1) + `benchmark.md` eşik onayı (Kadir).
- **İlgili:** `plan.md` Faz 1 · `benchmark.md`.

### BL-003 — EXP-001 ham-çıktı kalıcılığı (iyileştirme)
- **Sorun:** EXP-001 ölçümü ad-hoc script + testlerle üretildi; kalıcı JSON dump saklanmadı.
- **Öneri:** `analyze_document`/`extract_tables` çıktısını `reports/` altına JSON olarak yazan küçük bir "analiz dökümü" ekle (tekrar-üretilebilirlik).
- **İlgili:** `reports/EXP-001-*.md` §8.

### BL-004 — Test suite süresi
- **Sorun:** integration testleri kitabı birden çok kez parse ediyor (~3-4 dk).
- **Öneri:** paylaşılan parse cache / fixture; ya da adım-bazlı hedefli test.
- **İlgili:** `hezarfen_rag/tests/integration/`.

### BL-005 — EXP-009 eksik ölçümleri (üretici LLM adayları)
- **Yapıldı:** NVIDIA NIM ücretsiz uçlarda 3 model tam ölçüldü (96 çağrı/model, ürünün
  gerçek promptlarıyla); sağlayıcı env'den seçilebilir hale getirildi (`LLM_*`), 15 test.
  Rapor: `reports/EXP-009-uretici-llm-karsilastirma.md`.
- **Kalan:** (a) `moonshotai/kimi-k3` ölçümü — ilk koşumda paylaşılan NVIDIA kotası
  yüzünden 0/96 tamamlandı, tek başına yeniden koşuluyor; (b) **asıl karar ölçümü**:
  `data/` LFS'ten geri yüklendikten sonra aynı 200-item golden set'le TAM boru hattı
  (`python -m src.eval.runner`, `.env`'de `LLM_MODEL` değiştirilerek) her aday için
  koşulmalı — EXP-009 yalnız üreticiyi izole etti, retrieval ölçülmedi.
- **Sonraki kesin adım:** `gh auth login` → `git lfs pull` → 3 aday için runner.
- **İlgili:** `docs/OPTIMIZATION.md` §15 · `outputs/EXP-009-model-karsilastirma/`.

### BL-006 — Bu makinede (Fedora) ortam farkları
- **Yapıldı:** `.venv` kuruldu (Python **3.13**, CPU-torch 2.14, FlagEmbedding, deepeval);
  `tests/unit` **434 yeşil**. `.env` anahtar adları ASCII'ye çevrildi.
- **GPU ÇALIŞIYOR (2026-09-11).** Sürücü zaten kuruluydu (NVRM 610.57.04, RTX 4060
  Laptop 8 GB, CUDA UMD 13.3); `nvidia-smi` görünmüyordu çünkü kabuk Flatpak
  sandbox'ında ve host `/run/host` altında. `.venv`'e `torch==2.14.0+cu130` kuruldu
  (`/tmp` 1,6 GB tmpfs olduğu için ilk deneme `Errno 28` ile çöktü → `TMPDIR`
  `/home`'a alındı). **Ölçülen:** embed **49,8 chunk/s** (CPU 4,1 → 12×),
  rerank **1,90 s**/40 aday, `build_canonical` 194 sayfa **31,0 s**, VRAM tepe
  2.627 MB. `LD_LIBRARY_PATH` gerekmiyor.
- **CPU embed ÖLÇÜLDÜ (2026-09-10, artık tarihsel):** BGE-M3 CPU'da **~4,1 chunk/s** (16 chunk / 3,9 s;
  1024-dim, L2-norm 1,000 — GPU değeriyle aynı çıktı). Belgelenen GPU: 67 chunk/s →
  **~16× yavaş**; 12-bio'nun 258 chunk'ı ≈ **63 s** (kabul edilebilir). Model ilk indirme
  11,5 dk (2,3 GB). Reranker (cross-encoder, 40 aday × 200 sorgu) CPU'da asıl darboğaz olacak.
- **Kalan/riskler:** (a) **NVIDIA sürücüsü yok** (`nvidia-smi` yok, donanım var) → BGE-M3 +
  reranker **CPU'da** koşacak; ölçüm SÜRELERİ belgelenmiş GPU sayılarıyla KARŞILAŞTIRILAMAZ
  (kalite metrikleri etkilenmez — aynı model, aynı çıktı).
  (b) Proje 3.11 varsayıyordu, burada 3.11 paketi yok → 3.13 ile koşuluyor.
  (c) `tesseract` kurulu değil → OCR yolu (Faz 0.8) bu makinede sınanamaz.
  (d) HF model önbelleği Flatpak sandbox'ına düşüyor
  (`~/.var/app/com.vscodium.codium/cache/huggingface`) → kalıcı bir `HF_HOME` verilmesi iyi olur.
- **Sonraki kesin adım:** Kadir kararı — sürücü kurulsun mu (GPU ölçüm eşitliği için) yoksa
  CPU'da mı ölçelim (yavaş ama kalite metrikleri aynı).

### BL-007 — EXP-010 ürün-hazırlık denetimi: 62 bulgu, 36'sı MVP engeli
- **Yapıldı:** 4 boyutlu düşmanca denetim (güvenlik · grounding/atıf · değerlendirme ·
  operasyon), proje kuralı 18'e uygun ayrı `verifier`/`evaluator` bağlamlarında;
  bulguların çoğu **koşarak/hesaplanarak** doğrulandı. Rapor + issue taslakları:
  `reports/EXP-010-urun-hazirlik-denetimi.md`. Ürün kriterleri (iki kademe) Obsidian
  `rag/benchmark.md §8`'e, literatür geliştirmeleri `OPTIMIZATION.md §I`'ye yazıldı.
- **Kalan:** 36 MVP engelinin tamamı. Sıra: **M0** ölçüm güvenilirliği → **M1** güvenlik
  → **M2** atıf/grounding → **M3** golden set + testler → **M4** operasyon →
  **M5** kapı ölçümü + Kadir onayı (fazlar ve issue taslakları raporun §7'sinde).
- **Sonraki kesin adım:** GitHub auth gelince EPIC + faz issue'ları açılır
  (`gh issue create`), sonra **M0-1** (metriklere %95 CI) ile başlanır — çünkü o
  düzelmeden hiçbir kapı kararı verilemez.
- **Kadir'den bekleyen kararlar:** (a) `benchmark.md §8` kriterleri onayı,
  (b) kriz hattı numarası/metni (#M1-4), (c) prompt↔metrik çelişkisi kararı (#M2-9),
  (d) golden set v2 onayı (#M5-4), (e) NVIDIA sürücüsü kurulsun mu (CPU'da mı ölçelim).

## Ertelenen
- **Faz 4 — Soru üretme + benzer soru:** ⏸️ Kadir kararıyla ertelendi (2026-08-31). Tasarım hazır: `soru-uretme.md`.

### BL-008 — `top_n` yeniden kalibrasyonu (sayfa hizalı chunk'lamanın bedeli)
**Kaynak:** EXP-011 ablation'ı (#53), 2026-09-11 · **Durum:** AÇIK · **Bağlı:** #60, #92

Sayfa hizalı chunk'lama atıf sayfa-hassasiyetini kurtardı (teorik tavan
0,723 → 1,000) ama **bağlam hacmini daralttı**: gerçek kitapla ölçüldü, top-5
toplam token **1331 → 1110 (−%16,6)**; korpusun %13,1'i <50 token oldu (şekil
sayfası / bölüm kapağı gibi az metinli sayfalar).

Yuva işgali beklenenden küçük çıktı (sorgu başına 0,09 yuva, sorguların %9'u),
yani sorun minik chunk'ların top-k'yı doldurması **değil**, üretici modele giden
toplam kanıtın azalması.

**Yapılacak:** `top_n`'i sabit 6'da bırakmak yerine ölçerek seç. Tek başına
büyütmek doğru değil — maliyeti ve Lost-in-the-Middle riskini artırır. Bu yüzden
**#60 (çekimserlik eşiği kalibrasyonu) ile BİRLİKTE** ve golden set üzerinde
ölçülmeli → **#92 çözülmeden koşulamaz**.

**Kabul:** aynı golden set, `top_n ∈ {6, 8, 10}` × abstain eşiği taraması;
`recall@k` ve `answer_correctness` yükselirken `precision_page` ve maliyet/istek
kapı içinde kalmalı. Kapı kararı 95% CI alt sınırıyla verilir.

### BL-009 — Korpus ↔ kazanım müfredat uyuşmazlığı
**Kaynak:** EXP-012, 2026-09-11 · **Durum:** AÇIK · **Karar Kadir'de**

`kitap.pdf` yeni müfredattan (tema tabanlı: "1. Tema ENERJİ"), `kazanimlar.json`
eskisinden (ünite + `10.1.1.2` kodlaması). Ölçüldü: 10. sınıf biyoloji kitabında
**"mitoz" 0 kez** geçiyor, kazanım dosyası ünite 1'de "Mitozu açıklar" diyor.
Kazanım kapsamı: biyoloji %71, fizik %92, kimya %96, coğrafya/felsefe %100.

**Neden engel:** kapsanmayan kazanımdan golden set item'ı ya da öğrenci notu
üretilirse ürün doğru davranıp çekimser kalır, ama sonuç RAG başarısızlığı gibi
okunur. Kazanım kodları ileride ilerleme takibinin omurgası olacak (EduKG /
kişisel graf) — yanlış eşleşme haritayı baştan bozar.

**Yapılacak (karar gerekiyor):** yeni müfredatın kazanımları mı indirilecek,
yoksa eski müfredat kitapları mı? `eba_dl` yeniden koşulacaksa bu da alınmalı.
Geçici önlem uygulandı: `senaryo.kapsanan_kazanimlar()` kapsanmayanları eliyor.

### BL-010 — Köprü (hab/2) istemcisi yazılmadı
**Kaynak:** `docs/BACKEND-ENTEGRASYON.md`, 2026-09-11 · **Durum:** AÇIK

Backend QUIC **sunucusudur**, AI servisleri ona dial eder. Mevcut FastAPI
servisimizi backend çağırmaz. `src/backend/istemci.py` çerçeve kurma/çözme
kısmını taşımadan bağımsız hazır tutuyor; eksik olan QUIC taşıması,
`Hello`/`Greeting` el sıkışması ve `Request` döngüsü.

**Bağımlılık:** `AI_SHARED_TOKEN`, TLS sertifikası ve ayakta bir backend
(compose'da `AI_QUIC_ADDR: 0.0.0.0:8090`).

### BL-011 — Veli (parent) görünürlüğü kurulmadı
**Kaynak:** `src/backend/okul.py`, 2026-09-11 · **Durum:** AÇIK

Sahte okulda `parent_links` üretiliyor ama veli `/classes`, `/courses`,
`/notes` uçlarından **hiçbir şey göremiyor** (ölçüldü: üçü de `total=0`).
Sebep: velinin çocuğunun verisine backend'de hangi uçtan eriştiği henüz
doğrulanmadı (`domain/parent_link.rs` var, web yolu incelenmedi).

Boş bırakmak bilinçli: uydurulmuş bir veli görünürlüğü, üzerine kurulacak her
izolasyon ölçümünü sessizce geçersiz kılardı. Ürün hiyerarşisinde
`parent < student` olduğu için veli yolu MVP kapsamındadır.

**Yapılacak:** backend'de veli uçlarını okuyup `OkulSahtesi`'ne gerçek kuralı
koymak; `can_access`'in veli dalını ölçümle doğrulamak.
