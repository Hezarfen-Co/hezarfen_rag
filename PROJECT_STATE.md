# PROJECT_STATE

> Bu dosya `hezarfen_rag` repo'sunundur. Kardeş repolar: `hezarfen_backend`,
> `hezarfen_frontend`, `Hezarfen-Rule-Based-Chatbot`. RAG (retrieval-augmented
> generation) servisi + özet + guardrail burada; **aktif geliştirmede, uçtan uca
> çalışan + ölçülen boru hattı VAR** (aşağı).

## 1. Anlık Durum (2026-09-05, checkpoint)
- Aktif branch: `main` (tek-branch, adım adım commit; feature-branch yok)
- **Tek cümle:** Uçtan uca RAG + özet + guardrail + değerlendirme ÇALIŞIYOR ve 200-item
  golden set'e karşı ÖLÇÜLDÜ (retrieval recall@20 0.96, faithfulness 0.99, guardrail
  zararlı/injection 33/33·12/12, kasa izolasyonu 0-sızıntı); vertical slice = 12-biyoloji.
- **Kod (`src/`):** ingest/canonical/chunk (Faz 0) · embed BGE-M3 GPU (1.2) · index
  Qdrant+BM25 (1.3) · retrieve hibrit RRF + **kasa izolasyonu** (1.4/1.6) · rerank (1.5) ·
  generate **kaynak-sınırlı+atıf+fail-closed** (1.7) · guard **zararlı+injection+rol+LLM-sınıflandırıcı**
  (1.7b) · summarize **kanıtlı özet** (RAPTOR-benzeri) · memory **history-rewrite** · context
  **lost-in-middle+budget** · cache (Response/Embedding) · eval **DeepEval+DeepSeek-hakem** ·
  pricing/costlog. **316 birim testi yeşil.**
- **Değerlendirme:** `tests/golden/golden_12bio_v1.json` (200 item TASLAK, Kadir onayı bekliyor);
  `tests/evaluation/results/` re-baseline'lar; ölçümler Obsidian `deney-sonuclari.md`+`Maliyet.md`.
- **Agentic + optimizasyon:** `.claude/agents/` (Opus+Sonnet) + `docs/ORCHESTRATION.md`+`OPTIMIZATION.md`
  + `reports/RES-001/002/003` (kuzey-yıldızı ürün mimarisi). Sürekli-optimizasyon loop'u aktif.
- **DEEPSEEK_API_KEY** `.env`'de (doğrulandı). **Bekleyen (Kadir):** golden v1.1 onayı + kriz-hattı no'su.
- **Non-blocked optimizasyon BİTTİ** (citation P1 maxed + endpoint sözleşmesi). Sırada Kadir yönü (§10 menü):
  servis endpoint'i + kalıcı store, çok-dersli/RAPTOR ölçek, özet-PDF/OCR, ya da iki bekleyenin çözümü.

## 2. Hedef ve Kapsam
- **Ana hedef (niyet, repo adından):** öğretmenin yüklediği ders kaynağı üzerinden öğrencinin RAG ile sohbet edebildiği servis.
- **Tamamlanma tanımı:** kaynak alınır → indekslenir → sorgu retrieval + rerank yapar → kaynak-sınırlı+atıflı cevap üretilir → guardrail + kasa izolasyonu uygulanır. **Vertical slice (12-biyoloji) uçtan uca ÇALIŞIYOR ve ÖLÇÜLDÜ** (§1). Üretim tanımı için kalan: kalıcı store + servis girişi + backend entegrasyonu (bkz. §6).
- **Kapsam dışı:** kaynak YÜKLEME arayüzü/deposu — bu zaten VAR (bkz. §5 D1, course-notes); RAG servisi onu tüketecek, yeniden inşa etmeyecek. Backend/frontend repolarına DOKUNULMAZ.
- **Değiştirilemez kısıt:** tek branch (`main`), commit'lerde AI izi yok (yazar=Kadir); rol SUNUCU-tarafı türetilir (istemciye güvenilmez); pass-bias/over-correction yasak; benchmark/mimari/bulgular kilidi (Kadir onayı). org `Hezarfen-Co`.

## 3. Çalıştırma ve Doğrulama
- **Ortam:** `.venv` (proje-yerel), GPU torch cu124 (RTX 4060, cuda doğrulandı). Modeller: BGE-M3 (embed) + BGE-reranker-v2-m3 (rerank), GPU. `DEEPSEEK_API_KEY` `.env`'de.
- **Testler:** `python -m pytest -q` → **316 birim testi yeşil**. Değerlendirme: `python -m src.eval.runner` (golden set'e karşı; `GOLDEN_PATH` ile override).
- **Servis girişi:** henüz kütüphane (Generator/Summarizer import edilir); QUIC/HTTP endpoint + kalıcı Qdrant Faz-1-sonrası (bkz. `docs/API-CONTRACT.md`). Kök `../compose.yaml`'da `rag` servisi henüz YOK.

## 4. Mimari Özet
- **Mevcut (uygulandı, `src/`):** ingest/canonical/chunk → embed (BGE-M3 GPU) → index (Qdrant embedded + BM25) → hibrit RRF retrieval + **kasa izolasyonu** → rerank (BGE-reranker) → generate (kaynak-sınırlı + `[N]` atıf + fail-closed) → guard (zararlı + injection + rol + LLM-sınıflandırıcı). Ayrıca: summarize (kanıtlı özet, RAPTOR-benzeri), memory (history-rewrite), context (lost-in-middle + budget), cache (Response/Embedding), eval (DeepEval + DeepSeek-hakem), pricing/costlog.
- **Doğrulanmış kaynak (RAG için hazır girdi):** `course-notes` — öğretmen (kursu yönetebilen) yükler, **kursa kayıtlı öğrenci okur**, dosya ekli (PDF dahil, `FILES_PATH` volume). Backend: `hezarfen_backend/src/web/course_notes.rs`, `src/domain/course_note{,_file}.rs`. Frontend: `hezarfen_frontend/src/api/course-notes/*`.
- **Entegrasyon deseni (PLANLANAN / DOĞRULANMADI):** Çelebi chatbot'u gibi backend'in QUIC "hab/1" köprüsüne dial-in edip bir capability (ör. `rag.reply`) register etmesi olası (bkz. `hezarfen_backend/src/ai/registry`). Bu bir varsayımdır; repoda kanıt YOK. Endpoint girdi/çıktı sözleşmesi: `docs/API-CONTRACT.md`.

```mermaid
flowchart LR
  T[Öğretmen] -->|course-note yükle| BE[(backend course-notes + FILES_PATH)]
  BE -. korpus .-> RAG[hezarfen_rag - PLANLANAN]
  RAG -. index/embed/retrieve .-> RAG
  S[Öğrenci] -->|soru| FE[frontend] --> BR[backend QUIC hab/1] --> RAG --> BR --> FE --> S
  classDef todo stroke-dasharray: 5 5;
  class RAG todo;
```
> Diyagram NİYETİ gösterir; `RAG` kutusu ve kesikli oklar henüz **uygulanmadı**.

## 5. Teknik Kararlar
- **D1** — RAG kaynağı sıfırdan yükleme alanı GEREKMEZ: `course-notes` (öğretmen→kayıtlı-öğrenci, dosya ekli) doğal korpustur. **kabul edildi** (backend/frontend main'de doğrulandı 2026-08-16). ⚠️ **Çelişki düzeltmesi:** bu oturumun erken RAG cevabı "böyle bir alan yok" idi; o cevap course-notes eklenmeden önceki duruma aitti ve **artık geçersiz** — doğrulanmış gerçek: alan VAR.
- **D2** — Retrieval/embedding/vektör-store/LLM: **KARAR VERİLDİ** — hibrit (dense BGE-M3 + BM25) RRF + BGE-reranker-v2-m3; vektör-store Qdrant (şu an embedded, üretimde kalıcı); generatör DeepSeek (fine-tuning YOK). **kabul edildi + uygulandı + ölçüldü**.
- **D3** — Köprü mü / kendi HTTP API'si mi: **AÇIK** (Kadir kararı). Sözleşme hazır (`docs/API-CONTRACT.md`); QUIC-capability `rag.reply` varsayımı güçlü ama doğrulanmadı.

## 6. Aktif Görev
- **ID:** TASK-RAG-CHECKPOINT
- **Amaç:** non-blocked optimizasyon kalemleri tamamlandı; Kadir'in yön/onayı bekleniyor.
- **Kabul kriterleri:** karşılandı — uçtan uca boru hattı + 200-item ölçüm + 316 test yeşil + endpoint sözleşmesi.
- **Gerçek test sonucu:** §1 (recall@20 0.96, faithfulness 0.99, guardrail 33/33·12/12, kasa 0-sızıntı).
- **Durum:** `KADİR ONAYI/YÖNÜ BEKLİYOR` — non-blocked iş kalmadı; diminishing returns veri-onaylı.
- **Sonraki kesin işlem:** Kadir yön versin (aşağı §10 menü) VEYA iki bekleyeni çözsün (golden v1.1 onayı + kriz-hattı no'su).

## 7. Görev Kuyruğu (Kadir yönüne bağlı)
- **TASK-GOLDEN-APPROVE** — P1 — golden v1.1 (200 item) Kadir onayı → üretim ölçümü kilidi açılır. dep: Kadir. **BLOCKED**.
- **TASK-CRISIS-LINE** — P1 — self-harm guardrail mesajına kriz-hattı no'su. dep: Kadir. **BLOCKED**.
- **TASK-RAG-SERVICE** — P2 — QUIC/HTTP endpoint + kalıcı Qdrant (sözleşme: `docs/API-CONTRACT.md`). dep: D3 kararı. **TODO**.
- **TASK-RAG-SCALE** — P3 — Faz 2 RAPTOR ölçek + çok-dersli korpus + özet-PDF/OCR (Faz 0.8). dep: Kadir yönü. **TODO**.
- **TASK-REARCH** — P4 — derin yeniden-mimari (EB-KOS/layout/kalibrasyon) — "optimizasyon fazı", Kadir'e ayrıldı. **DEFERRED**.

## 8. Tamamlanan İşler (son 10)
- `549c606` docs: RAG servis endpoint sözleşmesi (backend entegrasyonu)
- `b41e5c2` fix(generate): citation precision-nudge + A/B bulgusu (P1 maxed)
- `94177c0` docs: kasa izolasyonu tamam (guardrail #3) + PROJECT_STATE
- (önce) Faz 1.2–1.7 boru hattı + guard/cache/eval/summary/memory/context + 200-item golden + re-baseline'lar.

## 9. Bilinen Hatalar ve Riskler
- **RISK-01** — In-memory store: üretimde kalıcı Qdrant + incremental reindex gerekir (course-notes silme/güncelleme senkronu).
- **RISK-02** — Vertical slice tek-ders (12-biyoloji); çok-dersli ölçekte metrikler yeniden ölçülmeli.
- **RISK-03** — Golden set TASLAK (Kadir onayı yok) → üretim eşikleri henüz kilitlenemez.
- **NOT** — GitHub MCP bu oturumda bağlanamadı (auth header); issue akışı (kural 19) commit-referansıyla sonra bağlanacak.

## 10. Son Oturum Devri
- **Bu oturumda:** citation-precision P1 A/B ile maxed (b41e5c2); endpoint sözleşmesi yazıldı (549c606); PROJECT_STATE §2–10 gerçek olgun duruma güncellendi.
- **Değiştirilen dosyalar:** `src/generate/prompt.py`, `docs/OPTIMIZATION.md`, `docs/API-CONTRACT.md`, `PROJECT_STATE.md`.
- **Bekleyen (Kadir):** golden v1.1 onayı + kriz-hattı no'su.
- **Kadir'in yön menüsü:** (a) iki bekleyeni çöz → üretim ölçümü; (b) servis endpoint'i + kalıcı store (D3 kararı); (c) çok-dersli/RAPTOR ölçek; (d) özet-PDF/OCR (Faz 0.8); (e) derin yeniden-mimari fazı; (f) loop'u sürdür.
- **Yeni sohbetin ilk kesin adımı:** bu dosyayı oku; non-blocked optimizasyon bitti — Kadir §10 menüsünden yön verene dek yeni büyük iş başlatma (churn yasak). Küçük doğrulama/ölçüm serbest.
