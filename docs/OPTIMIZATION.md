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

14. **Measure-after-change re-baseline** ✅ (**EXP-008**, reports/EXP-008-rebaseline.md): denetim+özellik sonrası kimya re-ölçüm (EXP-005 ile kıyas). **Kritik değişiklikler GÜVENLİ:** #C1 (atıfsız→çekimser) yanlış-abstain'i ARTIRMADI (0/23), guardrail sabit (3/3·5/5), 23/23 cevaplandı. Küçük retrieval/citation kayması (#27 ingest chunk-değişimi + n=23 gürültü) → regresyon değil, onaylı-gold+ölçekte doğrulanacak. Bio full-eval bellek-watchdog'a takıldı (chrome; RAM boşalınca koşulacak).

12. **Çok-ders özet + multimodal özet** — özet ✅ TAMAM, multimodal-özet mimari ✅ / model ⚠️ (**EXP-006**, reports/EXP-006-cokders-multimodal-ozet.md): özet dersler arası genelleşiyor (kimya damıtma-tablolu detaylı özet, fizik ünite özeti, atıflı). Multimodal-özet mimarisi çalışıyor (gorsel_aciklama birim → resolve_scope → atıflı özet). **⚠️→✅ BULGU+FIX:** `deepseek-v4-flash-vision-exp` yoğun diyagramda tüm bütçeyi reasoning'e harcayıp BOŞ içerik döndürüyordu → **`reasoning_effort:"none"`** ile GİDERİLDİ (ampirik: s.37 len 0→2362; default_captioner DeepSeek yolunda enjekte, sağlayıcı-bağımsız). Kadir "exp-model yeter" (stabil VLM üretim fazına ertelendi). **Backlog:** tam-korpus caption batch; görsel-span atıf tam-eşleşme (citation-granülerlik); captioning'i diyagram sayfalarına hedefle.

15. **Üretici LLM aday karşılaştırması** ✅ ÇEKİRDEK TAMAM / ⏳ eksik ölçüm (**EXP-009**,
    2026-09-10, reports/EXP-009-uretici-llm-karsilastirma.md + outputs/EXP-009-model-karsilastirma/):
    `deney-sonuclari.md §4` boştu ve `mimari.md §0.1` üreticiyi "ADAY" sayıyor → NVIDIA NIM
    ücretsiz uçlarında **ürünün gerçek promptlarıyla** (guard-sınıflandırıcı · history-rewrite ·
    kaynak-sınırlı üretim) 96 çağrı/model, aynı golden item kümesi, temperature=0, maliyet **$0**.
    **BULGULAR:** (a) `nvidia/nemotron-3-super-120b-a12b` her boyutta birinci/eşit **ve en hızlı**
    (p50 1.94 s) — guard zararlı 15/15 + injection 12/12 + 0 yanlış-pozitif, atıf precision 1.000,
    0 hayalet atıf, 0 yanlış-çekimser; (b) `meta/muse-glimmer-30b` kalitede yakın ama 4-5× yavaş
    (p50 9.3 s) ve kaynağı neredeyse birebir kopyalıyor (gold-F1 0.97 → prompt "kendi cümlelerinle"
    diyor); (c) **`nvidia/nemotron-3.5-lightning-30b-a3b` REDDEDİLMELİ** — nefret söylemini
    "güvenli" saydı (2/3), intihar sorusunda bozuk JSON döndürüp fail-safe allow'a düştü,
    jailbreak'i kaçırdı, kategori/cevap metninde dil kirlenmesi (`violence_凶手`, `促进하여`),
    kaynak yokken 7/8 item'da cevap uydurdu; (d) **NVIDIA'daki DeepSeek uçları kullanılamaz**
    (flash 300 s timeout ×3, pro 201.5 s — DeepSeek'in kendi API'si 1.0 s); (e) ücretsiz uçta
    **model başına eşzamanlılık ≈1** (4 worker → %92 HTTP 429) → modeller-arası paralel/model-içi
    seri; (f) reasoning modelleri varsayılan ayarla **boş içerik** döndürüyor (EXP-006'nın aynısı)
    → `nvidia/*` için `chat_template_kwargs.thinking=false`, kimi/muse için `reasoning_effort=none`.
    **KOD:** sağlayıcı env'den seçilebilir oldu (`LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY`/
    `LLM_EXTRA_JSON`), `pricing`'e `deepseek-flash` alias + NIM `nim-free` girdisi, eval anahtar
    kontrolü sağlayıcı-bağımsız, `.env` anahtar adları ASCII'ye çevrildi (eskiden kod HİÇBİRİNİ
    okuyamıyordu), 15 yeni test. **SINIR (dürüst):** retrieval ÖLÇÜLMEDİ (`data/` LFS'ten geri
    yüklenmemişti, GPU sürücüsü yok) → T3 **oracle-bağlam vekili** (kaynak blokları `gold_cevap`'tan
    kurulu) = üst sınır ölçümü. **EKSİK:** `moonshotai/kimi-k3` bu makinede aynı NVIDIA anahtarını
    kullanan İKİNCİ bir oturum yüzünden 96 çağrının yalnız 5'ini tamamladı → **ölçülemedi**, tek
    başına yeniden koşulmalı. **KARAR ÖNERİSİ:** üretim modeli ŞİMDİ değişmesin; `data/` gelince
    aynı 200-item golden set'le TAM boru hattı üzerinde (`LLM_MODEL` ile) tekrarlanıp karar verilsin.
    **Metrik açığı:** parafraz çekimserlik `model_abstained` etiketi almıyor (`_looks_like_abstain`
    yalnız tam cümleyi tanıyor); ürün güvenliği etkilenmiyor (atıfsız → `ungrounded_no_citations`
    kapısı zaten çekimser döndürüyor) ama değerlendirmede iki kök neden karışıyor → parafraz
    toleransı önerisi Kadir onayında.

**Engeller (blocking):** ✅ `DEEPSEEK_API_KEY` — `.env`'de mevcut + **doğrulandı** (gerçek çağrı OK, costlog uçtan uca çalışıyor, 2026-09-05). ⏳ **Kalan tek engel: golden set Kadir onayı** (kalite metrikleri için). Döngü buna takılırsa: kod/altyapı hazırlanır, taslak Kadir onayına sunulur, onay gelince kalite ölçümü koşulur.

---

## I. Literatürden gelen geliştirmeler + dürüst değerlendirme (2026-09-11)

> Kaynak: Kadir'in taraması `Obsidian .../Akıllı Eğitim Literatür/RAG literatür.md`
> + `reports/RES-003` + EXP-001…010. Kapılar: Obsidian `rag/benchmark.md §8`.
> Bulgular: `reports/EXP-010-urun-hazirlik-denetimi.md`. **Durum: KADİR ONAYI BEKLİYOR.**
>
> **Sıra kuralı (Kadir kararı):** önce ürün kriterleri + testler + değerlendirmeler +
> hata/eksikler; SONRA bu bölümdeki geliştirmeler. İstisna: §I.1 ve §I.7 zaten
> kapanmayan bir kapının kök nedeni olduğu için MVP içindedir.

### I.0 Önce dürüst çerçeve: literatürün bize söylediği en önemli şey

Kadir'in taramasındaki §17 tablosu ve §20 sonucu, projenin kendi `RES-003`'üyle
neredeyse birebir aynı yere varıyor: **merkezde "iyi ingest + hibrit + reranker"
olur; graph / hiyerarşik / düzeltici yollar sorguya göre çağrılan uzman rotalardır.**
Projenin `mimari.md §0.1` kararı da bu — yani **mimari yön değişmiyor, eksik parçalar takılıyor.**

Üç uyarıyı baştan yazıyorum, çünkü yol haritasının okunuşunu değiştiriyor:

1. **EduChatQA'nın sayıları hedef DEĞİL.** Raporladığı faithfulness **0,71** ve
   context precision@5 **0,52**, bizim ölçtüğümüz değerlerin (0,988 / — ) altında.
   O çalışma bize **mimari referans** verir, kalite hedefi vermez. "EduChatQA
   seviyesine çıkmak" bir gerileme olurdu.
2. **Bizim yüksek skorlarımız da güvenilir değil** (bkz. `reports/EXP-010-urun-hazirlik-denetimi.md` EVAL-03/04/05):
   hiçbir kapıda güven aralığı yok, faithfulness n=21 ve çekimser item'lar paydadan
   düşüyor. Yani **iki tarafın sayıları da şu an kıyaslanamaz.** Önce ölçüm düzelir.
3. **Khanmigo dersi bu yol haritasının en pahalı maddesini önceliksizleştiriyor:**
   *daha fazla içerik/link kazanç vermedi, yapılandırılmış öğrenci bağlamı verdi
   (+%6,1).* Bu, "daha çok retrieval yeteneği ekle" içgüdüsüne karşı somut bir kanıt.

---

### I.1 RAGFlow-tarzı ingest (deep document understanding) — **MVP · ÖNCELİK 1**

**Değerlendirmem: ✅ En yüksek getirili, en az riskli iş. Bu bir "geliştirme" değil, kapanmayan kapının kök nedeni.**

Neden bu kadar önemli: denetim, bilinen en büyük açığın (**citation precision 0,645**,
kapı 0,99) kök nedenini buldu — atıflar **chunk düzeyinde** ve child chunk'lar
**sayfa sınırını serbestçe aşıyor**; bu yüzden her atıf fazladan sayfa taşıyor
(ölçüm: item başına ortalama **0,94 fazla sayfa**; teorik tavan **0,712**). Yani
0,99 kapısı mevcut chunk'lamayla **matematiksel olarak imkânsız**. Embedding modelini
büyütmek bunu düzeltmez — literatürün "garbage chunk in → garbage RAG out" dersi tam bu.

**Kapsam (küçük adımlar):**
1. Child chunk'ları **sayfa sınırında zorunlu flush** → her child tek sayfaya bağlı (ACC-02)
2. Parent genişletmeyi **ayrı numaralı kaynak** yap (kendi sayfa aralığıyla) → model
   hangisini kullandığını atıflasın (ACC-03: kanıtlanmış yanlış-sayfa hatası)
3. İki sütun okuma sırasını **gerçek PDF üzerinde** doğrula (E-04, şu an ⚠️ şüphe)
4. Format çeşitliliği: `docx/pptx/xlsx/görsel` → ya destek ya **net red** (E-08)
5. Taranmış PDF yolu üretimde açık (OCR şu an `default-off`) + "okunamadı" bildirimi (E-01)
6. Tablo → satır-bazlı temsil (hücreye satır/sütun başlığı) — literatür §17 satırı
7. İçerik-hash ile tekilleştirme (E-05)

**Kabul paketi:** hedef kapı **A-02 / A-07 / K-01**; ablation = eski chunk'lama ↔ yeni,
aynı golden set; metrik = `precision_page`, `over_citation_rate` (yeni), `atıf→sayfa
doğruluğu` (insan ≥100 atıf); düşmanca senaryo = E-01…E-12; regresyon = K-01/K-04 düşmesin.
**Beklenen risk:** sayfa-sınırı flush'ı chunk sayısını artırır → recall@20 düşebilir.
Bu ölçülmeden alınmaz (bu yüzden ablation zorunlu).

---

### I.2 CRAG — Corrective Retrieval — **MVP · ÖNCELİK 2**

**Değerlendirmem: ✅ Literatürdeki en mantıklı öneri, ve zaten verilmiş bir kararın uygulanması.**

`OPTIMIZATION.md §E` şunu karara bağlamış: *"kanıt yetersizse (≤2-3 tur) sorgu
yeniden-yazma + yeniden-retrieval; hâlâ yetersizse çekimser"*. CRAG bunun literatürdeki
adı. Şu an sistemde **ikili** bir kapı var (kanıt var / yok) ve o kapının eşiği
(`abstain_score=0.30`) **kalibre değil** — denetim, eşiğin BGE-reranker sigmoid
ölçeğinde logit −0,85'e karşılık geldiğini hesapladı: **belirgin biçimde alakasız
çiftler bile geçiyor.** CRAG'ın üç durumu (`correct / ambiguous / incorrect`) bu boşluğu
tam dolduruyor.

**Bizim uyarlamamız (paperdan sapma, gerekçeli):**
- **Web fallback YOK.** Kapalı-kaynak kuralı (`mimari.md` §2.4: "yalnız MEB kaynak
  havuzu; web yok"). `incorrect` durumunda rota: sorgu yeniden-yazma → yeniden retrieval
  (≤2 tur) → hâlâ kötüyse **çekimser**. Bu, ürün sözünü bozmayan tek biçim.
- Değerlendirici olarak **önce ucuz sinyal** (rerank skoru + kanal uzlaşması + skor
  marjı), yalnız sınırda LLM'e sor → maliyet kontrolü (§F kaldıraçları).
- `decompose/recompose` (gereksiz bilgiyi ayıklama) bizde kısmen var
  (`context/packing.py`); CRAG'ın knowledge-strip fikri buna eklenir.

**Kabul paketi:** hedef kapı **C-02 / C-04 / C-05 / A-04**; baseline = mevcut ikili
kapı; ablation = CRAG kapalı ↔ açık; metrik = `cevaplanamazda yanlış cevap oranı`
(kapı ≤%5 MVP), `yanlış çekimserlik` (≤%5), ek gecikme p95, ek $/istek;
düşmanca senaryo = E-28 (makul görünen cevapsız soru), E-29 (çelişkili kaynak),
E-27 (spam → maliyet), CRAG'ın kendisinin yanlış "correct" demesi.
**Ön koşul:** golden set'e **20 alan-içi-cevapsız** item eklenmeli (EVAL-12: mevcut
"cevapsız" item'ların hepsi alan-dışı ve `insufficient_data` ile *tesadüfen* geçiyor).

---

### I.3 Self-RAG — **MVP'de PARÇALI, tam hâli KAPSAM DIŞI**

**Değerlendirmem: ⚠️ Fikri değerli, yöntemi bize uymuyor. Ayrıştırıp iki parçasını alalım.**

Dürüst gerekçe: Self-RAG, modeli **reflection token'ları** (`Retrieve?`, `IsRel`,
`IsSup`, `IsUse`) üretecek şekilde **eğitmeye** dayanıyor. Projenin değiştirilemez
kısıtı **"fine-tuning HİÇ YOK"** (`mimari.md` §1, Kadir kararı). Yani paperdaki yöntem
alınamaz — bunu "alınabilir" diye yazmak yanlış olurdu. Ama Self-RAG'ın *karar noktaları*
bizde zaten eksik ve ikisi ayrı ayrı, eğitim gerektirmeden kurulabilir:

- **(a) "Retrieval gerekli mi?" yönlendiricisi** — selam, "sen kimsin", "önceki cevabı
  tekrar et" gibi turlarda retrieval+LLM boşa harcanıyor. Bizde `understand/query_understanding.py`
  (kural-tabanlı intent) VAR; ona bir `retrieval_gerekli: bool` çıkışı eklenir.
  **Ucuz, ölçülebilir, maliyet düşürür.** → MVP.
- **(b) "Cevap kanıt tarafından destekleniyor mu?" — claim verifier.** Bu, Self-RAG'ın
  `IsSup` token'ının eğitimsiz karşılığı ve `RES-003 §3`'ün zaten istediği şey.
  Denetim bunun yokluğunun somut sonucunu ölçtü: **5 cümlenin 4'ü atıfsız olduğu hâlde
  cevap kullanıcıya sunuldu** (ACC-07) ve o cümlelerin 3'ü olgusal olarak yanlıştı.
  → MVP (kapı **A-03/A-05**).

Self-RAG'ın adı altında yapılmayacak: eğitimli reflection, öz-eleştiri döngüsü
(maliyet), "kendi kendini geçir" mantığı.

**Kabul paketi (a):** metrik = retrieval atlanan tur oranı + o turlarda kalite düşüşü
YOK kanıtı (aksi hâlde geri alınır); düşmanca senaryo = E-24 (zamir yığını yanlışlıkla
"retrieval gerekmez" sayılırsa cevap bozulur).
**Kabul paketi (b):** metrik = `atıfsız cümle oranı` (kapı ≤%10 MVP, ≤%1 TAM),
`unsupported_claim_rate` (≤%2 / ≤%0,5); ablation = verifier kapalı ↔ açık;
bedel = ek LLM çağrısı → p95 ve $/istek ölçülür; düşmanca senaryo = verifier'ın
doğru cümleyi silmesi (yanlış pozitif) → `yanlış çekimserlik` kapısı korunmalı.

---

### I.4 RAPTOR (hiyerarşik indeks) — **MVP SONRASI · ön koşullu**

**Değerlendirmem: ✅ Doğru fikir, ama bizde YARIM uygulanmış ve şu an ÖLÇÜLEMEZ.**

Durum: `summarize/` içinde "RAPTOR-benzeri" özyinelemeli **özetleme** var. Literatürün
asıl önerdiği şey ise hiyerarşik bir **retrieval indeksi** (detay chunk + üst-seviye
özet aynı indekste, sorgu ikisinden de çekebilir). Bizde bu yok.

İki sert gerçek:
1. **Ölçülemez.** Golden set'te **global/özet kategorisinde 0 item** var (EVAL-01,
   hesaplandı). "Bu ünitenin tamamı ne anlatıyor?" tipi soru hiç ölçülmüyor →
   RAPTOR'un kazancını gösterecek metrik YOK. Kabul paketi §3 gereği bu hâliyle
   üretime alınamaz.
2. **Bizdeki mevcut özet katmanının atıfları UYDURMA** (ACC-01, koşarak kanıtlandı):
   `_merge_summaries` modelin `[N]`'ini hiç okumuyor, atıfları kanıtı olan tüm
   ara-özetlerden üretiyor. RAPTOR'u indekse taşımadan önce bu kapanmalı, yoksa
   halüsinasyon yüzeyi büyür (`mimari.md §0.1`: *"özet düğümü hakikat kaydı değil"*).

**Sıra:** (i) ACC-01 düzelt → (ii) golden set'e **20 global/özet item** ekle
(`beklenen_kazanim_kapsami` alanıyla) → (iii) RAPTOR'u retrieval katmanı olarak ekle,
**atıf her zaman yaprak span'a çözülür** → (iv) ablation.

**Kabul paketi:** hedef kapı **A-08/A-09/A-10 + K-01**; metrik = global sorularda
`kazanım kapsamı` + `kaynak-destekli iddia oranı`; bedel = indeksleme sırasında
LLM özetleme maliyeti (kitap başına ölçülür, `Maliyet.md`); düşmanca senaryo =
özet düğümünün yanlış bilgiyi "otoriter" göstermesi, iki katman arası çelişki.

---

### I.5 HippoRAG / Curriculum-Graph retrieval — **MVP SONRASI · bizim özel avantajımız var**

**Değerlendirmem: ⚠️ Mekanizması (PPR) uygulanabilir; ingest'i (LLM ile entity çıkarımı) bize GEREKSİZ ve riskli.**

HippoRAG passage'lardan LLM ile bir bilgi grafı çıkarıp Personalized PageRank
koşuyor. Bizde **bedava ve insan-curate edilmiş bir graf zaten var**:
`curriculum/graph.py` → `kazanimlar.json`, **3505 kazanım / 54 ders**,
`sınıf→ders→ünite→kazanım` omurgası. LLM ile entity çıkarmak, elimizde MEB'in resmî
müfredat grafı varken **daha gürültülü** bir grafı para vererek üretmek olur.

Dolayısıyla önerim: **HippoRAG'ın PPR fikrini müfredat grafı üzerine uygula** —
kazanım↔chunk bağları kurulur, sorgudaki kazanım/kavram düğümlerinden PPR ile
komşu kazanımların chunk'ları çekilir. Bu aynı zamanda **EduChatQA'nın "curriculum
knowledge graph" bileşeni** ile aynı şey; iki literatür maddesi tek işte birleşiyor.
`mimari.md §0.1` bunu zaten "yalnız çok-adımlı/önkoşul sorularda ve ablation kazancı
kanıtlanırsa" diye koşula bağlamış — o koşul aynen geçerli.

**Sert ön koşul:** ölçülemez durumda. Denetim, `multi_hop` etiketli 18 item'ın
**11'inin tek sayfadan cevaplanabildiğini** hesapladı (EVAL-10) — yani "multi-hop
kapısı" şu an sahte geçiyor. Gerçek çok-atlamalı (≥2 ünite/sayfa) item'lar
eklenmeden graph retrieval'ın kazancı ölçülemez.

**Kabul paketi:** hedef kapı **K-06 + yeni `all_evidence_recall@20`**; ablation =
graph rotası kapalı ↔ açık, YALNIZ çok-atlamalı dilimde; bedel = ek gecikme;
düşmanca senaryo = graph'ın yapısal gürültü üretmesi (GraphRAG-Bench'in ders kitabında
gösterdiği başarısızlık — `RES-001` bunu not etmiş), yanlış önkoşul zinciri,
`ders`/`sınıf` sınırını graph üzerinden atlama (**kasa izolasyonu graph kenarlarında da
uygulanmalı** — yeni bir güvenlik yüzeyi).

---

### I.6 EduChatQA mimarisi — **parça parça, çoğu zaten var**

**Değerlendirmem: ✅ Mimari referans olarak çok değerli; bileşenlerinin yarısı bizde mevcut.**

| EduChatQA bileşeni | Bizdeki durum | Karar |
|---|---|---|
| Topic detector | `understand/query_understanding.py` (kural-tabanlı intent+NER) | ✅ var, genişletilir (§3a) |
| "Relevant conversation only" | `memory/window.py` + history-rewrite | ✅ var; **7+ tur hiç test edilmemiş** (EVAL-16) |
| BM25 + Dense | ✅ var | — |
| **Learnable fusion** | RRF (öğrenilmez) | ❌ **ALMIYORUM**: etiketli eğitim verisi yok, "fine-tuning yok" kısıtı; RRF literatürde de güçlü baseline |
| Curriculum passages | metadata filtresi ✅ | — |
| **Knowledge graph** | `curriculum/graph.py` var ama **retrieval'a bağlı DEĞİL** | → §5 |
| Teacher/Student prompt | tek prompt | → §7 (pedagojik politika) |
| **Answerability head** | fail-closed + çekimser var ama **kalibre değil** | → §2 (CRAG) + kapı **C-05 (ECE ≤0,05)** |

---

### I.7 Pedagojik dil politikası (literatür §16) — **MVP** (Kadir kararı)

**Değerlendirmem: ✅ Kadir'in MVP'ye alma kararı doğru ve ölçülebilir — ama dikkat: bu kapı grounding'le GERİLİMDE.**

Literatür §16: öğrenciler RAG cevaplarını beğeniyor, ama cevap **ders kitabının diline
fazla sıkı bağlıysa** tercih düşüyor. Ürün ayrımı: *RAG kanıtı belirler; tutor kanıta
sadık kalarak öğrenci seviyesinde anlatır.*

EXP-009 bunun ölçülebilir olduğunu gösterdi: `muse-glimmer-30b`'nin gold-cevapla
token-F1'i **0,857** (kaynağı neredeyse yeniden üretiyor), `nemotron-3-super`'in
**0,634** (özetliyor). Yani "kopyalama" bir sayı olarak izlenebiliyor.

**Dürüst gerilim uyarısı:** kopyalamayı azaltmak faithfulness ve atıf doğruluğunu
düşürebilir (model kendi cümlesini kurarken kanıttan sapabilir). Bu yüzden P-01
kapısı **tek başına** ölçülmez; A-04 (faithfulness) ve A-03 (atıfsız cümle) ile
**birlikte** raporlanır. Biri yükselip diğeri düşerse iş geri alınır.

**Kabul paketi:** metrik = `kopyalama oranı` (LCS/n-gram, yeni), okunabilirlik
(sınıf seviyesi), öğretmen onay oranı (≥50 cevap); ablation = mevcut prompt ↔
pedagojik prompt; düşmanca senaryo = E-65 (birebir kopya), sadeleştirirken bilimsel
hata (en tehlikelisi), terim kaybı, "çocukça" ton.

---

### I.8 Öğrenci modeli / kişiselleştirme (TutorLLM · Khanmigo · EduKG+PersonalKG) — **MVP SONRASI · AYRI SERVİS**

**Değerlendirmem: ✅ Ürünün gerçek farklılaşması burada. Ama mimari ve hukuki olarak RAG'in İÇİNE konulamaz.**

Kadir bunu "çok çok önemli" dedi; katılıyorum — ve tam bu yüzden yanlış yere
konulmaması gerekiyor. Üç somut gerekçe:

1. **Khanmigo kanıtı**: yapılandırılmış öğrenci bağlamı **+%6,1** next-item correctness
   verdi; daha fazla içerik/link **ölçülebilir kazanç vermedi**. Yani kişiselleştirme,
   "daha çok retrieval" işlerinden **daha yüksek getirili** — ama ancak öğrenci verisi
   gerçekten varsa.
2. **Veri bizde HAZIR ve backend'de**: `hezarfen_backend` zaten kurs/sınav/soru-bankası/
   yoklama/ödev tutuyor (mastery, yanlış cevaplar, prerequisite ilerleme). Yani
   **Personal KG'yi sıfırdan üretmek gerekmiyor**; backend'den okunur. Yeni bir izleme
   altyapısı kurmak gereksiz iş olurdu.
3. **KVKK (bu bir engel, tercih değil)**: öğrencinin bilgi durumu, reşit olmayan bir
   kişiye ait **özel nitelikli çıkarım**. `RES-003` bunu zaten şart koşmuş:
   *"öğrenci profili + adaptif veri evidence-corpus'tan FİZİKSEL + MANTIKSAL ayrı"*.
   Denetim, bugün bile bunun ihlal edildiğini buldu: self-harm sınıflandırma etiketi ve
   öğrenci sorgusunun ilk 30 karakteri **maliyet defterine düz metin** yazılıyor (SEC-10).
   Kişiselleştirmeye geçmeden bu kapanmalı.

**Önerdiğim mimari (RES-003 §18 ile uyumlu):**
```
EduKG (müfredat grafı)          Personal KG (öğrenci durumu)
kazanimlar.json                 backend: mastery/hata/önkoşul/deneme
= paylaşılan, kamusal           = kişisel, ayrı store, ayrı ACL, saklama süreli
        │                                   │
        └──────► RAG kanıt paketi ◄─────────┘  (yalnız PROMPT KURULUMUNDA buluşur)
                        │                       kanıt korpusuna KARIŞMAZ
                  Pedagojik politika  (explain / socratic / hint / quiz)
                        │
                       LLM → claim verifier → cevap → öğrenme çıktısı kaydı
```

**Kabul paketi:** hedef metrik **öğrenme çıktısı** (Khanmigo dersi: nihai metrik
Context Recall değil, öğrencinin öğrenmesi) → pilot A/B: kişiselleştirme kapalı ↔
açık, ölçüt = sonraki soru doğruluğu + öğretmen değerlendirmesi;
düşmanca senaryo = yanlış öğrenci modeli yüzünden yanlış seviyede cevap, damgalama
("sen bunu bilmiyorsun"), veri sızıntısı (E-45/E-46), veli erişimi sınırı,
model öğrencinin zayıflığını başka öğrenciye sızdırması.
**Ön koşul:** G-11/G-12 (KVKK) kapanmış + MVP tamamlanmış olmalı.

---

### I.9 ALMIYORUM / erteliyorum (gerekçeli)

| Öneri | Karar | Gerekçe |
|---|---|---|
| **GraphRAG (Microsoft) global search** varsayılan | ❌ | `mimari.md §0.1` + literatür §4'ün kendi uyarısı: her sorguyu graph'a göndermek hata; ders kitabında yapısal gürültü kötüleştiriyor (GraphRAG-Bench). Yalnız §5'teki koşullu rota. |
| **LightRAG** | ⏸️ | §5 (curriculum graph + PPR) aynı ihtiyacı **bedava ve daha temiz** karşılıyor. Kazanç kanıtlanırsa yeniden bakılır. |
| **Learnable fusion** (EduChatQA) | ❌ | Etiketli eğitim verisi yok; "fine-tuning yok" kısıtı. RRF güçlü baseline. |
| **Self-RAG eğitimli model** | ❌ | Fine-tuning kısıtı (Kadir kararı). Parçalı hâli §3'te. |
| **CRAG web fallback** | ❌ | Kapalı-kaynak kuralı (`mimari.md §2.4`). İç düzeltici retrieval alınıyor. |
| **HippoRAG LLM entity çıkarımı** | ❌ | Elimizde resmî müfredat grafı varken daha gürültülü bir graf üretmek. PPR mekanizması alınıyor. |
| **1M-token context'e tüm kitabı basmak** | ❌ | Literatür §19 (Lost in the Middle) + bizde `context/packing.py` zaten minimal-yeterli kanıt yaklaşımında. |
| **ColPali/ColQwen görsel retrieval** | ⏸️ | `mimari.md`: TR'de kanıtsız + ağır. Multimodal captioning (EXP-004) yeterli görülüyor; şekil/tablo golden item'ları gelince yeniden değerlendirilir. |

---

### I.10 Sıralı yol haritası (küçük adımlar → issue'lar)

> Her satır bir GitHub issue olacak (`gh issue create`). MVP kapsamı issue
> etiketleriyle belirlenir: `mvp` / `mvp-blocker` / `post-mvp`.
> Ayrıntılı adım listesi ve issue metinleri: `reports/EXP-010-urun-hazirlik-denetimi.md §7`.

**Faz M0 — Ölçüm güvenilirliği (hiçbir şey bundan önce gelmez)**
Gerekçe: `reports/EXP-010-urun-hazirlik-denetimi.md` EVAL-03/04/05/08/09/13 — bugün elimizdeki hiçbir sayı kapı
kararı için kullanılamaz. Önce terazi düzelir.

**Faz M1 — Güvenlik engelleri**
SEC-01/02 (özet+soru yollarında kasa izolasyonu bypass), SEC-03/04 (kendine-zarar
kaçışları), SEC-05 (özet/soru yollarında injection savunması yok), SEC-10 (KVKK).

**Faz M2 — Atıf/grounding kök nedenleri**
ACC-02 (sayfa-hizalı chunk = §1), ACC-03 (parent → yanlış sayfa), ACC-01 (özet atıf
uydurması), ACC-07 (atıfsız cümle), ACC-06 (çeşitlilik recall kaybı).

**Faz M3 — Golden set + testler**
Eksik kategoriler (şekil/tablo, global/özet, adversarial, alan-içi-cevapsız,
hard-negative, derin çok-turlu) + 13 yeni test dosyası.

**Faz M4 — Operasyon**
Kalıcı store, silme/güncelleme, oran+maliyet tavanı, hata yolları, yük testi.

**Faz M5 — MVP kapı ölçümü + Kadir onayı**

**Faz P1+ (MVP sonrası, Kadir'in verdiği sıra)**
CRAG tamamlama → Self-RAG router → RAPTOR retrieval katmanı → Curriculum-graph/PPR →
EduChatQA answerability kalibrasyonu → öğrenci modeli/kişiselleştirme.
