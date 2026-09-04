# OPTIMIZATION.md — Standing kararlar + optimizasyon backlog'u

> Sürekli-optimizasyon döngüsünün (bkz. `ORCHESTRATION.md` §7) yürüttüğü plan.
> Kadir'in tekrar prompt yazmasına gerek yok; kararlar burada gömülü, döngü işler.
> Ölçümler Obsidian `deney-sonuclari.md`/`Maliyet.md`'ye; süreç burada.

## A. Değerlendirme altyapısı — DeepEval metrikleri (GitHub #16)

**Felsefe:** pass-bias YASAK. Amaç eksiği görmek. Metrik eksiği göremiyorsa yenisi eklenir.
DeepEval hakem-LLM'i olarak **DeepSeek** kullanılır (custom model; `DEEPSEEK_API_KEY` gerekir).

**Retrieval metrikleri (golden set gerektirir):**
| Metrik | Ölçtüğü | Hedef (ilk) |
|---|---|---|
| ContextualRecall | Gerekli kanıt getirilenlerde mi | ≥ 0.90 |
| ContextualPrecision | Getirilenlerin ne kadarı ilgili + üstte | ≥ 0.75 |
| ContextualRelevancy | Getirilen bağlam soruyla ilgili mi | ≥ 0.70 |
| (özel) Recall@20 / nDCG@10 / MRR | Retrieval + rerank sıralama kalitesi | recall ≥0.98 / nDCG ≥0.90 |

**Üretim metrikleri:**
| Metrik | Ölçtüğü | Hedef |
|---|---|---|
| Faithfulness | Cevap bağlama sadık mı (halüsinasyon yok) | ≥ 0.95 |
| AnswerRelevancy | Cevap soruyu karşılıyor mu | ≥ 0.80 |
| Hallucination | Bağlam-dışı uydurma | ≤ 0.05 |
| (özel) Citation precision/recall | İddia → gerçek span (sayfa/bbox) bağı | ≥ 0.95 / ≥ 0.90 |

**Güvenlik/guardrail metrikleri (G-Eval / özel, DeepEval):**
| Metrik | Ölçtüğü | Hedef |
|---|---|---|
| Kapsam-dışı red | Eğitim-dışı soruya çekimser mi | ≥ 0.99 |
| Zararlı-içerik red | Güvensiz isteğe uygun red (reşit-olmayan kitle) | ≥ 0.99 |
| Rol-sızıntısı | Rolün göremeyeceği içerik sızıyor mu | **0 (kesin)** |
| Fail-closed | Dayanak yoksa LLM çağrılmıyor mu | %100 |

**Harness:** RagArt'ın L1-L4 deseni + DeepEval. Ucuz deterministik kapılar (format, dil,
citation-span var mı) → embedding metrikleri → pahalı LLM-hakem yalnız `critical` örneklerde
(maliyet). Asla-çökmez sarmalayıcı; her katman ayrı raporlanır (otomatik ≠ LLM-hakem ≠ insan).
**Bağımlılık:** golden set (aşağıda) + `DEEPSEEK_API_KEY`.

## B. Golden set (GitHub #16'nın önkoşulu; plan Faz 1.8)

- ≥30 örnek (sonra büyüt): soru + zorunlu kanıt span('lar)ı + gold cevap + kategori
  (kolay/orta/zor, edge_case, critical) + beklenen davranış (cevapla / çekimser / red).
- **Sızıntısız bölme.** Türkçe, 12-bio dikey diliminden başla.
- Bootstrap: `evaluator` taslak üretir → **Kadir onayı** (benchmark kilidi, SHARED_RULES 10).
- Bu olmadan A'daki kalite metrikleri ölçülemez → döngünün ilk büyük boşluğu.

## C. Cache (GitHub'da issue aç) — RagArt'tan uyarlanmış

- **EmbeddingCache** `(model,text)→vektör`, TTL ∞: indeksleme + sorgu embed'ini amortize eder.
- **ResponseCache** exact-match (soru+rol+model+strateji+k+seçili kaynak): **DeepSeek çağrısını sıfırlar** — en büyük maliyet kazancı.
- **SemanticCache** opt-in (cosine ≥0.95): RagArt O(N) tarıyordu → biz **Qdrant koleksiyonu** olarak (ANN).
- Backend SQLite (zero-dep). **RagArt'ın boşluğu:** canlı token/$ telemetrisi yoktu → biz `costlog` ile her çağrıda ekleriz.

## D. Prompt engineering (GitHub'da issue) — ürün: kaynakla-konuşma + kanıtlı özet

- **Direct + atıf (temel):** kaynak-sınırlı, `[N]` atıf ÜRETTİR (RagArt atıfı yasaklıyordu = boşluk), fail-closed, 3. tekil. Atıf **doğrulanır** (§A citation).
- **Query-rewrite:** ucuz recall artışı (orijinal güvenlik ağı) — önerilen.
- **Few-shot:** "kanıtlı özet" formatını + atıf disiplinini dayatmak için — önerilen.
- **HyDE / step-back / multi-query:** KOŞULLU — yalnız golden-set eval kazancı kanıtlarsa (§0.1 uyarlamalı; maliyet/fayda ölç).
- **Self-refine:** yalnız yüksek-paydaş (pahalı).
- Karar: Direct+atıf + Query-rewrite + Few-shot ile başla; diğerlerini eval kazancıyla ekle.

## E. Agent / ReAct kararı (Kadir'in sorusu)

İki ayrı "agent" var:
1. **Geliştirme-zamanı agentic sistem** (Opus orkestratör + Sonnet kodcu...) → EVET, kuruldu (`ORCHESTRATION.md`).
2. **Çalışma-zamanı (üründe) agent / ReAct?** → **Tam ReAct HAYIR.** Gerekçe: açık-uçlu tool-use ReAct maliyet + gecikme + halüsinasyon riski; ürün fail-closed + atıf-zorunlu. Bunun yerine mimari §0.1'deki **sınırlı agentic**: kanıt yetersizse (≤2-3 tur) sorgu yeniden-yazma + yeniden-retrieval; hâlâ yetersizse **çekimser**. İç mekanizma, kullanıcıya tool-loop göstermez. GraphRAG yalnız çok-adımlı/önkoşul sorularında ve ablation kazanç kanıtlarsa.
- Ölçüt: sınırlı-agentic yalnız recall/faithfulness'ı golden-set'te ispatlanabilir artırıyorsa açık kalır; maliyeti buna değmiyorsa kapatılır.

## F. Maliyet optimizasyon kaldıraçları

Prompt cache (sabit sistem+few-shot), ResponseCache (tekrar sorular), off-peak toplu iş,
model seçimi (kolay=flash/zor=pro; modül başına ölç), top-k/bağlam kısaltma (kaliteyi izleyerek),
küçük→parent genişletme (precision+bağlam). Her değişiklik `Maliyet.md`'ye "ne değişti→etki".

## G. Öncelikli backlog (döngü sırası)

1. **Golden set v0 bootstrap** (B) — Kadir onayına sun. *(kalite ölçümünün önkoşulu)*
2. **DeepEval harness** (A, #16) — golden set gelince retrieval+üretim+güvenlik metrikleri.
3. **Guardrail/güvenlik katmanı** (kapsam-dışı + zararlı + rol-sızıntısı + fail-closed) — üretimle (Faz 1.7) beraber. *(reşit-olmayan kitle → kritik)*
4. **Üretim + atıf** (Faz 1.7, #15) — DeepSeek, `[N]` atıf + doğrulama, fail-closed. *(DEEPSEEK_API_KEY)*
5. **Cache** (C) — ResponseCache + EmbeddingCache + costlog telemetri.
6. **Faz 1.4/1.5 kalite ölçümü** (#12/#13 reopen) — golden set gelince recall/nDCG + rerank kazancı.
7. **Prompt strateji A/B** (D) — query-rewrite/few-shot kazancını ölç.
8. **Sınırlı-agentic** (E) — ablation ile kanıtla ya da kapat.
9. **Observability** (#18) + **test piramidi** (#17).

**Engeller (blocking):** `DEEPSEEK_API_KEY` (üretim + DeepEval hakem), golden set Kadir onayı.
Döngü bunlara takılırsa: kod/altyapı hazırlanır, ölçüm anahtarı/onay gelince koşulur.
