# RAG — Deney Sonuçları & Başarı Kriterleri (DOLDURULACAK)

Amaç: her aşamanın **iyi mi kötü mü** çalıştığını sayıyla görmek, **başarı
kriterini geçene kadar optimize etmek**, ve "ne değiştirdik da bu sonucu aldık"
(neden-sonuç) kaydını tutmak.

> Son güncelleme: **2026-08-21** · Durum: **kod yok — tablolar deneyler başlayınca doldurulacak**
> İlgili: [[rag/gorevler]] · [[maliyet-ve-sunucu]] · [[test-tablolari]]

## Nasıl doldurulur
Her deneyde: **config** (model/boyut/chunk/top-k/reranker…) → **DeepEval skorları**
→ **token'lar** (input/output/thinking) → **Not: ne değişti → sonuç**. Kriteri
geçtiyse Durum ✅, geçmediyse ❌ ve neyi deneyeceğini yaz.

---

## 1) Başarı kriterleri (GEÇENE KADAR OPTİMİZE) 🎯
| Aşama | Metrik (DeepEval) | Hedef eşik (taslak) | Güncel | Durum |
|---|---|---|---|---|
| S1 Damıtma | Faithfulness (özet↔kaynak) | ≥ 0.90 | — | — |
| S2 Chunking | ContextualRecall | ≥ 0.80 | — | — |
| S3 Embedding | ContextualPrecision | ≥ 0.70 | — | — |
| S5 Retrieval | ContextualPrecision / Recall | ≥ 0.70 / ≥ 0.75 | — | — |
| S5 Retrieval | Yetkisiz-kurs sızıntısı | **0 (kesin)** | — | — |
| S6 Reranking | ContextualPrecision (rerank sonrası) | ≥ 0.85 | — | — |
| S8 Üretim | Faithfulness | ≥ 0.90 | — | — |
| S8 Üretim | AnswerRelevancy | ≥ 0.80 | — | — |
| S8 Üretim | Hallucination | ≤ 0.10 | — | — |
| Uçtan uca | Ortalama latency (sorgu) | ≤ 3 sn | — | — |
| Uçtan uca | Maliyet/sorgu | ≤ $___ | — | — |

> Eşikler taslak; #1 kararından sonra netleşir. Golden set: `hezarfen_rag/mockdata/` tabanlı ≥30 soru.

---

## 2) Uçtan-uca run kütüğü (end-to-end) 🧪
| Run | Tarih | LLM | Embed (model/dim) | Vektör/quant | chunk/overlap | top-k | rerank | in tok | out tok | think tok | Faith | AnsRel | CtxPrec | CtxRecall | Halüs | Latency | $/sorgu | Not (ne değişti → sonuç) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | | | | | | | | |
| _R1 (örnek)_ | _—_ | _Gemini 2.5_ | _e5/1024_ | _Qdrant/int8_ | _500/50_ | _5_ | _yok_ | _2400_ | _280_ | _0_ | _0.88_ | _0.83_ | _0.72_ | _0.70_ | _0.12_ | _2.1s_ | _$0.006_ | _rerank yok → CtxPrec düşük_ |

---

## 3) Aşama-aşama tablolar

### S1 — Veri damıtma (distillation)
| Deney | Yöntem | Sıkıştırma % | Faithfulness (özet↔kaynak) | Bilgi kaybı notu | Karar |
|---|---|---|---|---|---|
| | | | | | |

### S2 — Chunking
| Deney | chunk boyut (token) | overlap | metadata (JSON?) | ContextualRecall | Not (ne değişti → sonuç) |
|---|---|---|---|---|---|
| | | | | | |

### S3 — Embedding modeli / boyut
| Deney | Model | Boyut (dim) | CtxPrecision | CtxRecall | Sorgu latency | Depo boyutu | Not |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

### S4 — Vektör deposu / quantization
| Deney | Store | Quantization | Depo boyutu | Arama latency | recall@k | Doğruluk kaybı % | Not |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

### S5 — Retrieval (hybrid + rol filtresi)
| Deney | Yöntem (dense/sparse/hybrid) | Füzyon | top-k | CtxPrecision | CtxRecall | İzolasyon (sızıntı=0?) | Not |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

### S6 — Reranking
| Deney | Reranker | CtxPrec (önce) | CtxPrec (sonra) | Δ | Latency etkisi | Not |
|---|---|---|---|---|---|---|
| | | | | | | |

### S7 — Sorgu anlama (NER/intent/rewrite)
| Deney | Yöntem (rewrite/multi-query/HyDE) | Retrieval Δ (CtxRecall) | Not |
|---|---|---|---|
| | | | |

### S8 — Üretim & grounding
| Deney | LLM | Prompt sürümü | Faithfulness | AnswerRelevancy | Hallucination | Atıf doğru? | in/out/think tok | Not |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

---

## 4) LLM karşılaştırması (model seçimi) 🤖
| Model | in $/1M | out $/1M | think? | Faithfulness | AnswerRelevancy | Latency | $/sorgu | Not |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

> Maliyet detayları: [[maliyet-ve-sunucu]] §2.

---

## 5) Karar & çıkarımlar (özet)
Deneyler ilerledikçe buraya **hangi aşama iyi / kötü** ve **neden** yazılır:
- İyi çalışan aşamalar: __________
- Zayıf aşamalar + neden: __________
- Bir sonraki optimizasyon hedefi: __________

---

## 6) Analiz kayıtları (model-dışı — DeepEval tabloları henüz boş)
> Bu bölüm LLM çalıştırılmayan **ölçüm/analiz** kayıtlarıdır; yukarıdaki S1-S8 model
> tabloları ilk model deneyinde (Faz 1 / EXP-002) dolacak.

| ID | Tarih | Tür | Özet | Maliyet | Durum |
|---|---|---|---|---|---|
| EXP-001 | 2026-08-31 | ANALİZ (model yok) | Korpus görsel/tablo yoğunluğu: 12-bio %27 figür-ağırlıklı, %23 salt-metin; cross-ders kimya %5↔matematik %42; tablo 270 ham→az gerçek. Ayrıntı: `reports/EXP-001-*.md` | $0.00 | **İNSAN İNCELEMESİ BEKLİYOR** |
