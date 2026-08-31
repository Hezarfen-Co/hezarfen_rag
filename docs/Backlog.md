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

## Ertelenen
- **Faz 4 — Soru üretme + benzer soru:** ⏸️ Kadir kararıyla ertelendi (2026-08-31). Tasarım hazır: `soru-uretme.md`.
