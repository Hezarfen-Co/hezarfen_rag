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

**RE-BASELINE v1 (2026-09-05, golden_12bio_v1 190 item, $0.94):** istatistiksel güçlü. retrieval recall@20 span 0.966/sayfa 0.976 MRR 0.811; citation SAYFA P/R **0.645/0.886**; guardrail zararlı **33/33** (dolaylı dahil, LLM-sınıflandırıcı ölçekte sağlam); yanlış-abstain 1/123; faithfulness 0.983, correctness 0.825. **🔴 YENİ AÇIK: prompt_injection 2/12** (regex yakalıyor 2, LLM-sınıflandırıcı injection'ı kapsamıyordu) → **FIX ✅ (commit 4d95bcf):** sınıflandırıcıya prompt_injection eklendi → hedefli re-ölçüm **12/12** (regex 2 + LLM 10). multi_turn 5 item hafızasız 4/5 cevapladı → benchmark'ın multi_turn'ü zayıf (daha elliptik olmalı) + hafıza yine de gerekli.

**RE-BASELINE v1.1 (2026-09-05, 200 item, memory+context AÇIK, $1.10):** retrieval recall@20 span 0.961/sayfa 0.970; citation SAYFA 0.645/0.883; guardrail zararlı **33/33** + **injection 12/12** (fix ölçekte tuttu) + kapsam-dışı 16/16; faithfulness **0.988**, correctness 0.838. **HAFIZA A/B (elliptik multi_turn, n=10): rewrite OFF 0.90 → ON 1.00 recall@20 (+0.10).** DÜRÜST: kazanç mütevazı — 9/10 elliptik item rewrite'sız da 1.0 getirdi (küçük tek-ders korpusta vague sorgu bile konu-kelimesi taşıyor); net kazanç yalnız mt009 (konu-kelimesiz "bu ikisi arasındaki fark" 0→1.0). Hafızanın değeri: büyük/çok-ders korpus + saf-zamir takip + ÜRETİM netliği (A/B yalnız retrieval ölçtü). **context engineering** (lost-in-middle+budget) açıkken citation/faithfulness KORUNDU/arttı (0.988). ✅ memory + context TAMAM (kod+entegre+ölçüldü).

**OPTİMİZASYON ADIMLARI (öncelik sıralı):**
1. **Atıf:** (a) ✅ sayfa-düzeyi + overlap metriği (commit 5a3165b) → sayfa P/R 0.645/0.886 (v1.1). (b) ✅ prompt precision-nudge denendi + A/B ile ölçüldü (temp=0, n=22): precision **+0.008** (0.537→0.545), recall KORUNDU (0.818). **BULGU (dürüst):** citation-precision model aşırı-atıfından DEĞİL, **dar gold-set tanımından** sınırlı — model gold'da olmayan ama gerçekten ilgili komşu sayfaları atıflıyor (cevap meşru olarak birden çok sayfaya dayanıyor). Prompt ile daha fazla kazanç YOK. Gerçek kaldıraç: (i) çok-span/geniş gold tanımı VEYA (ii) daha dar top_n — ikisi de Kadir kararı. **Bu P1 fiilen maxed (diminishing returns DATA-ONAYLI).**
2. ~~Aşırı-abstain~~ ✅ GİDERİLDİ (commit fca0fb8): kök neden prompt'ta "kaynaklar YETERSİZSE bulunamadı de" fazla agresifti → "yalnız TAMAMEN alakasızsa abstain; kısmi bilgide cevapla". Doğrulama (gerçek DeepSeek): 5 yanlış-abstain 0/5→**5/5 cevap**; edge-case'ler 3/3 korundu (over-correction yok); birim 40/40. NOT: transient qdrant/CUDA segfault → pipeline run'ı retry gerektirdi (ayrı operasyonel risk).
3. ~~Guardrail zararlı-içerik~~ ✅ GİDERİLDİ (commit e6d7c02): LLM-güvenlik sınıflandırıcı (2. katman, DeepSeek) → zararlı red **1/3→3/3** (e05/e06 parafraz yakalandı). ⏳ *kalan:* golden set zararlı örneklerini genişlet (Kadir); kriz-hattı no'su; red-team suite.
4. ~~faithfulness fix~~ ✅ TAMAM (commit 9d5619f).
5. **Golden set (P1, Kadir):** TASLAK'ı doğrula/genişlet (bazı gold span'lar dar; 9 kazanım kapsanmadı); onayla → benchmark resmî olsun.
6. ~~Faz 1.6 kasa izolasyonu~~ ✅ GİDERİLDİ (commit 299681b, #22): can_access retrieval'e bağlandı (HybridRetriever meta+role_ctx filtresi). Gerçek retrieval doğrulaması: öğrenci-12, 100 chunk/5 sorgu HEPSİ sınıf-12, **0 yetkisiz sızıntı**. guardrail #3 kapandı.
7. **memory + context** ✅ (commit 21d21ea/0070407): history-rewrite (A/B +0.10, değeri ölçekte artar) + lost-in-middle + token budget.
8. ~~Çok-dersli ölçek + kasa izolasyonu~~ ✅ DOĞRULANDI (**EXP-002**, reports/EXP-002-cok-dersli-kasa-izolasyonu.md): 4 gerçek kitap (12-bio/kimya/fizik + 11-bio) birleşik indekste. **ders** boyutu 0/800 sızıntı (66 yabancı chunk filtresiz gelirdi), **sınıf** boyutu 0/800 (aynı ders çapraz-sınıf, 63 chunk); erişim-denemesi 4/4 fail-closed; ölçek bio recall'ı bozmadı. Kasa izolasyonu artık tek-ders/sentetik değil, çok-kitaplı gerçek retrieval'la kanıtlı.

**RE-BASELINE v1.1 sonrası açık (EXP-002'den, metrik):** ~~sayfa-recall@20 doygun~~ ✅ ÇÖZÜLDÜ (EXP-005/#24): **ayırt edici metrik = recall@5/@10 + MRR** (doygun değil; kimya @5=0.913, fizik @20=0.977, MRR 0.864/0.955). STANDING KARAR: retrieval değerlendirmesinde birincil metrikler recall@5/@10 + MRR (sayfa-recall@20 yalnız üst-sınır göstergesi).

9. ~~Faz 0.8 OCR + özet-PDF~~ ✅ TAMAM (**EXP-003**, commit 5d03c07, reports/EXP-003-ocr-ozet-pdf.md): OCR fallback (Tesseract-tur, `build_canonical(ocr=True)`, zarif degradasyon, default-off) — Türkçe yüksek-doğruluklu (bio s.2 OCR≈text-layer); sessiz-delik (taranmış/text-in-image) kapandı. HATA→FIX: tessdata quoting → TESSDATA_PREFIX env. Özet-PDF uçtan uca kanıtlı (build_canonical→resolve_scope→summarize, detaylı+atıflı+hiyerarşik, kapak sayfalarını dürüstçe ayırdı). **SINIR:** görsel-sanatlar içeriği görüntüde (multimodal, Faz 5) — OCR yalnız gömülü metni kurtarır. **Backlog:** uzun kapsamda max_tokens; OCR provenance CanonicalUnit'e.
10. **Faz 5 Multimodal VLM captioning** ✅ çekirdek TAMAM (**EXP-004**, #23, commit d6fb062+a4ea060, reports/EXP-004-multimodal-vlm-captioning.md): sağlayıcı-bağımsız VLMCaptioner (OpenAI-uyumlu) + `build_canonical(vlm=True)` → figure_heavy sayfalar `kind="gorsel_aciklama"` birim. **BULGU:** DeepSeek API'nin vision modeli var (`deepseek-v4-flash-vision-exp`, canlı /models) → **mevcut key yeter, yeni key YOK** (Kadir: yerel değil-API kararı böyle karşılandı). Canlı kanıt: görsel-sanatlar portre/etkinlik sayfaları doğru Türkçe betim, uydurma yok, ~$0.0008/sayfa. **Backlog:** tam-korpus captioning batch (maliyet-bilinçli, koşulmadı), figür-başı granülerlik, exp-model kalite izleme.
11. **Non-bio kalite + ayırt edici metrik** ✅ TAMAM (**EXP-005**, #24, commit 92f53bb, reports/EXP-005-nonbio-kalite-metrik.md): kimya+fizik gold TASLAK (kaynak-çıkarlı, insan-curate; Kadir onayı bekliyor). **BULGU:** RAG dersler arası GENELLEŞİYOR (bio-overfit değil) — kimya/fizik recall@20 0.98-1.0, MRR 0.86-0.96, 0 yanlış-çekimser, citation P/R bio bandında; guardrail domain-yakın zararlıyı (uyuşturucu/patlayıcı/nükleer) 3/3 reddetti, çekimser 5/5. Ayırt edici metrik = recall@5/@10+MRR (yukarı bkz). **Backlog:** gold Kadir onayı; citation-precision dar-gold sınırı.
13. **Tam denetim (yazılım+AI) + adversarial** ✅ (**EXP-007**, commit aeee583, reports/EXP-007-audit.md): 4 paralel review-agent + 3-parça fuzz. **DÜZELTİLEN (17, testli):** kasa izolasyonu fail-open→fail-closed, çok-turlu rewrite guard, injection-regex genişletme, newline-bypass, classifier robust-parse, indirect-injection prompt sertleştirme, **atıfsız cevap→çekimser** (grounding bütünlüğü), output-guard yanlış-pozitif, tr_normalize/cost_usd/deepseek-content/costlog/BM25/ocr-env/packing/summarizer/cache crash+doğruluk guard'ları. **1000-kullanıcı fuzz: 0 gerçek crash, guard 14/14 (0 bypass).** BACKLOG #26-#31 de 2. turda ÇÖZÜLDÜ: #26 visuals vektör-diyagram, #27 ingest sınıflama (core#5 güvenlik-gereği red), #28 costlog kilit+atomik, #29 eval runner/judge robustluk+test, #30 RAPTOR-proper özyineleme+cache-versiyon, #31 guard sertleştirme (fenced kaynak, strict role). **382 unit testi yeşil.** Tek kalan: judge.py DeepEval Deprecation (kütüphane drift, işlevsiz).

12. **Çok-ders özet + multimodal özet** — özet ✅ TAMAM, multimodal-özet mimari ✅ / model ⚠️ (**EXP-006**, reports/EXP-006-cokders-multimodal-ozet.md): özet dersler arası genelleşiyor (kimya damıtma-tablolu detaylı özet, fizik ünite özeti, atıflı). Multimodal-özet mimarisi çalışıyor (gorsel_aciklama birim → resolve_scope → atıflı özet). **⚠️→✅ BULGU+FIX:** `deepseek-v4-flash-vision-exp` yoğun diyagramda tüm bütçeyi reasoning'e harcayıp BOŞ içerik döndürüyordu → **`reasoning_effort:"none"`** ile GİDERİLDİ (ampirik: s.37 len 0→2362; default_captioner DeepSeek yolunda enjekte, sağlayıcı-bağımsız). Kadir "exp-model yeter" (stabil VLM üretim fazına ertelendi). **Backlog:** tam-korpus caption batch; görsel-span atıf tam-eşleşme (citation-granülerlik); captioning'i diyagram sayfalarına hedefle.

**Engeller (blocking):** ✅ `DEEPSEEK_API_KEY` — `.env`'de mevcut + **doğrulandı** (gerçek çağrı OK, costlog uçtan uca çalışıyor, 2026-09-05). ⏳ **Kalan tek engel: golden set Kadir onayı** (kalite metrikleri için). Döngü buna takılırsa: kod/altyapı hazırlanır, taslak Kadir onayına sunulur, onay gelince kalite ölçümü koşulur.
