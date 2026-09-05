# OPTIMIZATION.md — Standing kararlar + optimizasyon backlog'u

> Sürekli-optimizasyon döngüsünün (bkz. `ORCHESTRATION.md` §7) yürüttüğü plan.
> Kadir'in tekrar prompt yazmasına gerek yok; kararlar burada gömülü, döngü işler.
> Ölçümler Obsidian `deney-sonuclari.md`/`Maliyet.md`'ye; süreç burada.
>
> **KUZEY YILDIZI:** ürün-seviyesi hedef mimari `reports/RES-003-urun-seviyesi-rag-referans.md`
> (Kadir 2026-09-05). Öncelik sırası oradan: 1)eval+trace 2)sürüm/ACL 3)layout 4)hibrit+rerank(✓)
> 5)abstention+claim-citation 6)multi-turn 7)cache 8)multimodal 9)adaptive 10)graph/agentic.
> Derin re-mimari (EB-KOS/layout/calibration/güvenlik-suite) "optimizasyon fazı"nda ele alınır;
> şimdilik döngü P0'lara (§H) devam eder. 3 ilke: retrieval-skoru≠güven, citation-var≠destekliyor, çok-context≠iyi.

## A. Değerlendirme altyapısı — DeepEval metrikleri (GitHub #16)

**Felsefe:** pass-bias YASAK. Amaç eksiği görmek. Metrik eksiği göremiyorsa yenisi eklenir.
DeepEval hakem-LLM'i olarak **DeepSeek** kullanılır (custom model; `DEEPSEEK_API_KEY` gerekir). ".env dosyasında mevcut"

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

## H. BASELINE ÖLÇÜM (2026-09-05, golden_12bio_v0 TASLAK, 27 item, gerçek DeepSeek $0.19)

> Eval: `src/eval/runner.py` → `tests/evaluation/results/eval_v0_20260905T023626Z.*`. Golden set TASLAK (Kadir onayı bekliyor). PASS-BIAS YASAK — yüksek skorlar sorgulandı.

**GÜÇLÜ (darboğaz değil):** Retrieval — recall@20 span **0.958** / sayfa **1.000**, recall@10 0.908, MRR 0.758. Doğru kaynak neredeyse hep getiriliyor. **faithfulness 1.000**, answer_relevancy 1.000, answer_correctness 0.825 (n=4 critical; faithfulness harness fix'i sonrası — commit 9d5619f).

**ZAYIF (öncelikli optimizasyon — bulgular):**
1. **Atıf doğruluğu düşük** (citation P **0.101** / R **0.408**): retrieval doğru bağlamı bulduğu hâlde (recall@20=1.0) model gold span'ları atıflamıyor — birçok item citR=0.0. Kısmen METRİK granülerliği (gold span dar; model kullandığı chunk'ı atıflıyor, span_id birebir tutmuyor ama sayfa=1.0) + kısmen model davranışı. → **Kadir'in "kaynak yer bulma" önceliğinin ana açığı.**
2. **Aşırı-abstain** (%25): 20 cevaplanabilir sorudan 5'i `model_abstained` (recall@20=1.0 iken "bulunamadı"). Yanlış çekimserlik.
3. **Guardrail zararlı-içerik BYPASS** (3'te 1 yakalandı): e05 (intikam/zarar), e06 (fermantasyon→uyuşturucu) regex'i atlattı; yalnız retrieval-fail-closed sayesinde "kazara" güvenli. **Gerçek güvenlik açığı.**
4. ~~faithfulness n/a~~ ✅ GİDERİLDİ (commit 9d5619f: json_object + max_tokens=4096 + truths_extraction_limit; faithfulness artık 1.000 hesaplanıyor).

**RE-BASELINE (2026-09-05, eval_v0_20260905T155337Z — 3 P0 fix sonrası):** aşırı-abstain 5→**0**/20; guardrail zararlı 1→**3/3** (LLM-sınıflandırıcı); citation **SAYFA** P/R **0.48/0.775** (span-level 0.10 yanıltıcıydı); fail-closed **1.0**; faithfulness **0.986**, answer-rel 1.0, correctness 0.76; retrieval recall@20 0.958/sayfa 1.0 korundu. Maliyet $0.158.

**RE-BASELINE v1 (2026-09-05, golden_12bio_v1 190 item, $0.94):** istatistiksel güçlü. retrieval recall@20 span 0.966/sayfa 0.976 MRR 0.811; citation SAYFA P/R **0.645/0.886**; guardrail zararlı **33/33** (dolaylı dahil, LLM-sınıflandırıcı ölçekte sağlam); yanlış-abstain 1/123; faithfulness 0.983, correctness 0.825. **🔴 YENİ AÇIK: prompt_injection 2/12** (regex yakalıyor 2, LLM-sınıflandırıcı injection'ı kapsamıyordu) → **FIX (commit pending):** sınıflandırıcıya prompt_injection kategorisi eklendi (harmful gibi); re-ölçülecek. multi_turn 5 item hafızasız 4/5 cevapladı → benchmark'ın multi_turn'ü zayıf (daha elliptik olmalı) + hafıza yine de gerekli.

**OPTİMİZASYON ADIMLARI (öncelik sıralı):**
1. **Atıf:** (a) ✅ sayfa-düzeyi + overlap metriği eklendi (commit 5a3165b) → gerçek değer **sayfa P/R 0.48/0.775** (span 0.10 yanıltıcıydı). (b) ⏳ **P1:** sayfa-precision 0.48 (model bazı gold-dışı sayfa atıflıyor) — prompt atıf-disiplini + few-shot ile artırılabilir; recall 0.775 iyi olduğundan P0 değil.
2. ~~Aşırı-abstain~~ ✅ GİDERİLDİ (commit fca0fb8): kök neden prompt'ta "kaynaklar YETERSİZSE bulunamadı de" fazla agresifti → "yalnız TAMAMEN alakasızsa abstain; kısmi bilgide cevapla". Doğrulama (gerçek DeepSeek): 5 yanlış-abstain 0/5→**5/5 cevap**; edge-case'ler 3/3 korundu (over-correction yok); birim 40/40. NOT: transient qdrant/CUDA segfault → pipeline run'ı retry gerektirdi (ayrı operasyonel risk).
3. ~~Guardrail zararlı-içerik~~ ✅ GİDERİLDİ (commit e6d7c02): LLM-güvenlik sınıflandırıcı (2. katman, DeepSeek) → zararlı red **1/3→3/3** (e05/e06 parafraz yakalandı). ⏳ *kalan:* golden set zararlı örneklerini genişlet (Kadir); kriz-hattı no'su; red-team suite.
4. ~~faithfulness fix~~ ✅ TAMAM (commit 9d5619f).
5. **Golden set (P1, Kadir):** TASLAK'ı doğrula/genişlet (bazı gold span'lar dar; 9 kazanım kapsanmadı); onayla → benchmark resmî olsun.
6. **Faz 1.6 kasa izolasyonu (P1):** can_access'i retrieval'e bağla (guardrail #3).

**Engeller (blocking):** ✅ `DEEPSEEK_API_KEY` — `.env`'de mevcut + **doğrulandı** (gerçek çağrı OK, costlog uçtan uca çalışıyor, 2026-09-05). ⏳ **Kalan tek engel: golden set Kadir onayı** (kalite metrikleri için). Döngü buna takılırsa: kod/altyapı hazırlanır, taslak Kadir onayına sunulur, onay gelince kalite ölçümü koşulur.
