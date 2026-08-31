# RAG — Görevler (pipeline aşamaları)

GitHub: `Hezarfen-Co/hezarfen_rag` (epic #3). Bu dosya **üst düzey issue↔aşama**
haritasıdır. **Detaylı, commit-boyutunda küçük adımlar → [[plan]]** (literatüre
göre bölündü). Mimari → [[mimari]] / [[soru-uretme]]. Kapılar → [[benchmark]].

## Kararlar & iskelet
| Görev | Issue | Durum |
|---|---|---|
| Mimari kararlar (LLM / vektör / bağlantı) | #1 | **KARAR VERİLDİ** → [[mimari]] (DeepSeek-flash, BGE-M3, Qdrant, FT yok) |
| Servis iskeleti (`src/` + `tests/`) | #2 | **DONE** (7 birim test yeşil) |
| ~~Mock veri~~ | #7 | **GEREKMEZ** — gerçek veri indirildi (`data/`, tüm ders/sınıf); mock düştü |

## Pipeline aşamaları
| Aşama | Issue | Kalite ölçütü | Durum |
|---|---|---|---|
| S1 Veri damıtma (distillation) | #8 | DeepEval Faithfulness + sıkıştırma oranı | TODO |
| S2 Chunking (+JSON metadata) | #9 | ContextualRecall | TODO |
| S3 Embedding modeli/boyutu | #10 | precision/recall karşılaştırma | TODO |
| S4 Vektör deposu (+quantization) | #11 | boyut/latency/recall (<%5 kayıp) | TODO |
| S5 Retrieval (hybrid + rol filtresi) | #12 | ContextualPrecision/Recall + izolasyon | TODO |
| S6 Reranking | #13 | precision artışı | TODO |
| S7 Sorgu anlama (NER/intent/rewrite) | #14 | rewrite'lı vs değil | TODO |
| S8 Üretim & grounding (atıf) | #15 | Faithfulness/Hallucination/Relevancy | TODO |

## Kalite & test
| Görev | Issue | Durum |
|---|---|---|
| DeepEval eval harness + golden set | #16 | TODO |
| Test piramidi (unit/integration/e2e) | #17 | TODO |
| Observability (aşama latency/log) | #18 | TODO |
| EvoMaster black-box (backend) | backend#28 | TODO |

## Özellikler (üst düzey)
| Görev | Issue | Durum |
|---|---|---|
| Kaynakla-konuşan RAG | #4 | TODO |
| Benzer soru üretimi | #5 | TODO |
| Özet çıkartımı | #6 | TODO |
