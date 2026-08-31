# 📚 RAG Modülü — hezarfen_rag

Planlanan RAG servisi: **öğretmenin yüklediği ders kaynağıyla (course-notes)
öğrencinin RAG üzerinden sohbeti** + benzer-soru üretimi + özet çıkarımı.

> Son güncelleme: **2026-08-21** · Durum: **kod yok (%0)** · Mock veri hazır

## Durum
- Repo boş placeholder (tek commit). Mimari kararlar **verilmedi** (issue #1).
- **Mock veri hazır:** `hezarfen_rag/mockdata/` (4 ders, 8 ders notu, 24 soru) — backend course-notes / api-read şeklini taklit eder.
- Aşama-aşama, **literatür-temelli** görev planı çıkarıldı (bkz. [[rag/gorevler]]).

## Kaynak (nereden veri gelir)
Backend'de **course-notes** var (öğretmen yükler, kayıtlı öğrenci okur, PDF dahil).
RAG bunu HTTP'den değil, backend QUIC köprüsünün **api-read** kanalından çeker:
`GET /course-notes?course=...` + dosya blob, **read-only, rol-gated**
(`on_behalf_of=<öğrenci>`). Backend tarafı: issue `hezarfen_backend#27`.

## Verilecek kararlar (issue #1) — açık
1. **LLM:** yerel (offline/gizlilik) mı, API (Gemini/Claude, hız/kalite) mı?
2. **Vektör store:** Qdrant (öneri, scalar quantization) mı, SurrealDB v3 vektör mü?
3. **Bağlantı:** backend QUIC api-read (öneri) mı, ayrı HTTP mi?

## Pipeline (her aşama ayrı issue + literatür)
Damıtma → Chunking → Embedding → Vektör deposu → Retrieval → Reranking →
Sorgu anlama → Üretim/grounding → (kalite) DeepEval + Test + Observability.
Detay + issue eşlemesi: [[rag/gorevler]].

> **İlke:** issue'lardaki teknik adları yön göstericidir; her aşamaya gelince
> **güncel literatür taranır**, en iyi güncel yöntem birlikte seçilir.

## Kalite
- **DeepEval** metrikleri (faithfulness, contextual precision/recall, hallucination…) — [[test-tablolari]] §4.
- **EvoMaster** black-box sistem testi (backend REST) — [[test-tablolari]] §5.

## Maliyet
Depolama/token/sunucu çerçevesi: [[maliyet-ve-sunucu]].

## Alt sayfalar
- [[mimari]] — **RAG mimari kararı** (adaptive+hibrit+hiyerarşik+multimodal; DeepSeek-flash, FT yok) · kaynak [[Literatür/Hezarfen]]
- [[soru-uretme]] — **soru üretme mimarisi** (üretici/çözücü/eleştirici, yanılgı bankası, ret kapıları) · kaynak [[Literatür/Soru Üretme]]
- [[plan]] — **adım adım plan** (küçük adımlar, kabul kriterli, fazlı)
- [[benchmark]] — **katı değerlendirme** metrikleri + release kapıları + golden set
- [[bulgular]] — **korpus bulguları** (görsel/tablo/diyagram yoğunluğu → verimli LLM + doğru RAG besleme)
- [[Maliyet]] — **maliyet defteri** (her run birim maliyet; otomatik)
- [[rag/gorevler]] — aşama görevleri + durum (üst düzey; ayrıntı [[plan]]'da)
- [[rag/deney-sonuclari]] — başarı kriterleri + deney tabloları (DeepEval, token) — kalite kaydı
- [[rag/buglar]] — **bug takibi** (chatbot ile aynı format; kod geliştikçe dolar)
