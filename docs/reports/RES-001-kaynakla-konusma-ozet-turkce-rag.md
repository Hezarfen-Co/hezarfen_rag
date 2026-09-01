# RES-001 — Kaynakla Konuşma, Kanıtlı Özetleme ve Türkçe RAG Model Doğrulaması

> **Tür:** Derin literatür taraması + deney tasarımı · **Tarih:** 2026-08-31 (kayıt: 2026-09-01)
> **Durum:** Kadir incelemesi bekliyor. Bu rapor **mimari.md ve benchmark.md için değişiklik ÖNERİR** (o dosyalar kilitli — bkz. `Notes.md` onay kuyruğu).
> **Kapsam:** RAG-QA grounding/atıf/faithfulness, çok-turlu kaynakla konuşma, uzun-belge özetleme, RAPTOR, extract-then-abstract, FActScore/SummHay; BGE-M3, bge-reranker-v2-m3, DeepSeek-V4-Flash için **Türkçe kanıt düzeyi**.
> **Not:** "DeepSeek-flash" = DeepSeek-V4-Flash (Haz 2026) varsayıldı. Farklı SKU ise model kartı + deney matrisi yeniden sabitlenmeli.

## Yönetici özeti (4 madde)
1. **Omurga doğru yönde ama yayınlanabilir kanıt zinciri tanımlı değil.** Eklenmeli: her cevap cümlesini sabit kaynak span'ına bağlayan **claim–evidence sözleşmesi**, çok-turlu **sorgu durum çözümleyicisi**, ayrı **atıf doğruluğu/atıf tamlığı** ölçümü, **cevaplanamazlık kalibrasyonu**.
2. **RAPTOR güvenli özetleyici değil, retrieval yönlendiricisidir.** Son cevap/atıf her zaman **ham yaprak span'a** döner. Varsayılan: extract → seç/tekilleştir → abstract → claim doğrula → kapsam denetle.
3. **BGE-M3, bge-reranker-v2-m3, DeepSeek-V4-Flash için DOĞRUDAN Türkçe kaynak-grounding kanıtı YOK.** Bunlar "kanıtlanmış varsayılan" değil, **Türkçe gizli testte yarışacak ADAYLAR**dır (MIRACL/MLDR'de Türkçe yok; DeepSeek Türkçe atıf/faithfulness yayımlamaz).
4. **Karar için Türkçe hard-negative benchmark ZORUNLU** → `Hezarfen-RAG-TR-HN v1` (1.200 çok-modlu soru, belge-bazlı gizli ayrım, sayısal/negasyon/istisna/tablo/versiyon/çok-tur distractor, answerable–partial–unanswerable + claim-span altınları). Retrieval, rerank, oracle-context grounding, uçtan uca QA, konuşma ve özetleme **ayrı** ölçülür.

**İlk aday hat:** TR BM25/karakter n-gram + BGE-M3 dense/sparse → RRF → top-100 → reranker top-20/30 → kanıt yeterlilik kapısı → DeepSeek-V4-Flash High yapılandırılmış claim+span → bağımsız claim doğrulayıcı → onarım/abstention. **Karşısında Türkçe baseline şart:** multilingual-e5-large / TurkEmbed4Retrieval; Jina TR hard-negative reranker; gpt-oss-120B veya Gemma sınıfı üretici. Seçim ortalama skora göre değil, **dilim-bazlı %95 GA + kritik hata üst sınırı**na göre.

## Kanıt dereceleri
A=Doğrudan (aynı dil+model+görev) · B=Komşu (TR farklı model/sürüm ya da aynı model farklı dil) · C=Zayıf (küçük/sentetik/self-report) · D=Yok.

## 1. Çok-turlu kaynakla konuşma
Tek-tur RAG çok-tura taşınmaz (zamir, örtük özne, konu değişimi). Literatür: QReCC (NAACL21, query rewrite ayrı problem), TopiOCQA (TACL22, konu geçişi), **MTRAG (TACL25**: ilk-tur Recall@5 ~0.89 → sonraki tur ~0.47; rewrite iyileştirir ama ilk-tur seviyesine çıkarmaz), MTRAG-UN (ACL26, unanswerable/underspecified/non-standalone), CORAL (2024, sıkıştırılmış geçmiş atıf davranışını korur).
**Sonuç:** query rewriting **gerekli ama yetersiz**.

**Konuşma durumu sözleşmesi (her tur 4 nesne):** (1) kullanıcı ifadesi (değişmez), (2) konuşma durumu (varlık/zaman/kapsam/çıktı biçimi), (3) **bağımsız güncel sorgu** (zamir çözer ama önceki asistan cevabından olgu EKLEMEZ), (4) tur kanıt paketi (versiyonlu span).
**Kural:** önceki asistan cevabı **asla kanıt değildir**; belirsiz referansta clarification üret; konu değişiminde eski varlıkları sıfırla; her çözülen varlık hangi turdan geldiğiyle loglanır.
**Hata dilimleri:** zamir/eliptik, önceki kısıt koruma, yanlış eski cevap tuzağı, açık/örtük konu değişimi, belirsiz referans, kısmi kaynak, cevaplanamaz yakın komşu.

## 2. Grounding, atıf, faithfulness — 5 AYRI boyut
| Boyut | Soru | Birim |
|---|---|---|
| Retrieval evidence recall | Gerekli altın span getirildi mi? | soru/gold-set |
| Answer correctness | Cevap görev açısından doğru mu? | soru/claim |
| Claim support (faithfulness) | Claim, kanıtla destekleniyor mu? | atomik claim |
| Citation correctness | Atıf gerçekten o claim'i destekliyor mu? | claim–citation |
| Citation completeness | Destek gerektiren claim'ler atıflı mı? | ağırlıklı claim |

"Atıf desteği" ≠ "dünyada doğru". Güvenli ifade: **"Kaynak X'e göre…"** + kaynak sürümü görünür.
**Literatür:** ALCE (EMNLP23, citation recall/precision birlikte), Attributed QA/AutoAIS (2022, NLI sistem-seviyesi güçlü, örnek-seviyesi gürültülü), AttributionBench (2024, büyük judge tek başına çözmez), **GopherCite (2022: abstention kabul edilince destek kalitesi YÜKSELİR)**, RAGTruth (ACL24, retrieval ≠ faithfulness garantisi). Çerçeveler: RAGAS (hızlı regresyon, tek kapı değil), ARES (judge transferi dil/alan değişiminde zayıflar → **TR alan-içi 150–300+ insan etiketiyle kalibre**), RAGChecker (retriever↔generator hata ayrımı).

**Claim–evidence sözleşmesi:** `claim_id · claim_text · evidence_ids (1–3 versiyonlu span) · relation(entails/partial/contradicts) · criticality · confidence(kalibre değil)`. Kullanıcı metni bu yapıdan render; **alıntı = span koordinatından KODLA alınır** (model cümlesi değil). Doğrulama: atomikleştir → yalnız bağlı span'la test → sayı/birim/tarih/negasyon/istisna ayrı → 1 onarım → hâlâ desteksizse çıkar/abstain. **Bağımsız doğrulayıcı üreticiyle aynı model/prompt OLMAMALI** (ortak hata modu).

## 3. Uzun belge & özetleme
**RAPTOR (ICLR24):** QuALITY 82.6 (önceki 62.3); ama 150 özet düğümünde ~%4 halüsinasyon → **düğüm = navigasyon artefaktı, hakikat kaydı değil; son claim ham yaprak span'a bağlanır.**
SummN (ACL22, split-then-summarize), Context-Aware Hierarchical Merging (2025, birleşim halüsinasyonu büyütebilir → her aşamada ham kanıtla refresh), Faithfulness–Abstractiveness trade-off (ACL22, yüksek faithfulness çoğu zaman extractive → coverage/density raporla), LONGFORMFACT (2024, lost-in-the-middle → baş/orta/son + permütasyon testi), GraphRAG (2024, global tema soruları; tek ders özeti için varsayılan değil).
**Varsayılan hat (extract-then-abstract):** yapı-korumalı böl → kanıt birimi çıkar (ham span'a bağlı) → seç+tekilleştir → kapsam planı → kanıt-kısıtlı abstract (claim_id/evidence_id taşır) → claim doğrula → coverage denetle → render (inline atıf + sayfa/timestamp + sürüm). RAPTOR/GraphRAG yalnız 2–4. adıma aday içerik.
**Özet türleri ayrı değerlendirilir:** ders/bölüm · sınav notu · çok-kaynak sentezi · soruya-göre · kronolojik transcript. Tek ROUGE/tek judge yetmez.

## 4. Özet değerlendirmesi
**FActScore (EMNLP23):** desteklenen atomik olgu / toplam — precision ölçer, **kapsamı ölçmez** → salience/coverage ile eşle. LongDocFACTScore (LREC-COLING24, cümle başına retrieve+yerel doğrula, Kendall ~0.61). **SummHay (2024):** ~100 belge/93–100K token; insight coverage + atıf + joint; insan Joint ~56, oracle sistemler 10+ puan altında, retrieval'sız uzun-bağlam <20 → "hepsini uzun bağlama koy" **kaynaklı sentez garantisi vermez**. Stress Testing Factual Consistency (ACL26, hiçbir metrik negasyon/çok-span'da tutarlı güvenilir değil). MiniCheck (2024, 770M verimli checker; ikinci evaluator, tek kapı değil).
**Önerilen üçlü:** kaynak-bound otomatik claim doğrulama (≥2 farklı evaluator ailesi) + gold meaning-unit coverage & citation (programatik+LLM) + **kör Türkçe insan audit** (kritik claim'lerde uzman adjudication).

## 5. Türkçe kanıt — retrieval & reranking
- **BGE-M3** (Findings ACL24): 568M, 1024-dim, 8192 token, dense+sparse+multi-vector, 100+ dil. **MIRACL/MLDR'de Türkçe YOK** → **Kanıt B**.
- **bge-reranker-v2-m3** (~0.6B XLM-R): BEIR/C-MTEB/MIRACL; TR hedef değerlendirmesi yok → **B**. Topluluk TR fine-tune (215K triplet, self-report MAP 0.789/nDCG@10 0.842): hakemsiz, dar alan → **C** (yarışmacı).
- **TR-MTEB (EMNLP25):** BGE-M3 değerlendirilmez; retrieval nDCG@10: text-embedding-3-small 64.99 / **multilingual-e5-large 60.62** / gte-multilingual-base 57.51 → **TR sıralaması İngilizce'den varsayılamaz; e5 güçlü baseline.**
- **TurkEmbed4Retrieval (2025):** GTE-multilingual TR uyarlaması; SciFact-TR R@10 0.94 → baseline/aday.
- **Bridging the Language Gap in RAG (2025):** e5-large + Jina reranker TR fine-tune; **aşırı atomik chunking faithfulness'ı DÜŞÜRÜR**; alan-içi TR hard-negative kritik.
- **RAGTurk (SIGTURK26):** en iyi HyDE+cross-encoder+tree-summarize+long-context %85; cross-encoder rerank güvenilir kazanç, aşırı modül maliyeti artırıp skoru düşürür. **unanswerable sınıfı yok** → fail-closed için eksik.

## 6. Türkçe kanıt — DeepSeek-V4-Flash
Model kartı: ~284B toplam / **13B aktif** (MoE), 1M bağlam, MRCR/CorpusQA, düşünme seviyeleri. **YAYIMLANMAYAN:** TR benchmark, TR retrieval, span atıf precision/recall, claim-level source faithfulness, answerable/partial/unanswerable kalibrasyonu. (Rapordaki retrieval-search değerlendirmesi **V4-Pro** ve ağırlıkla Çince.) **1M bağlam ≠ grounding kanıtı.** Komşu: TurkBench (2026) **DeepSeek-V3.1** (V4-Flash değil) özet 80.1 / faithfulness 87.4 / genel 75.2 → olumlu ama dolaylı. → **Doğrudan D, aile-komşu B/C. Oracle-context + uçtan uca TR testten geçmeden varsayılan yapılmaz.**
**Donanım:** 13B "aktif" ≠ 13B bellekte; toplam MoE ağırlığı 8GB yerel GPU'ya sığmaz → **API/servis gerekir** (mahremiyet+gecikme+maliyet birlikte değerlendirilir).

## 7. Türkçe özetleme kanıtı
**TR-EduVSum (SIGTURK26):** 82 TR ders videosu, 3.281 insan özeti, transcript ort. 1.969 kelime; AutoMUP meaning-unit piramidi → **TR summary-coverage tohumu** (tek alan: veri yapıları/algoritmalar → tıp/mühendislik/tablo-slayt eklenmeli; atıf/factuality altın etiketi yok). **ImplicaTR (SIGTURK24):** 19.350 NLI (entailment/contradiction/neutral/implicature) → claim-verifier'ın **dilsel adversarial** (sayı/modal/nicelik/negasyon) testi.

## 8. Hezarfen-RAG-TR-HN v1 (önerilen benchmark)
**Dağılım (≥1.200):** tek-hop answerable %55 (660) · çok-hop/karşılaştırma %20 (240) · partial %10 (120) · unanswerable %15 (180). Kaynak: PDF/not, tablo/şekil, slayt, transcript+timestamp, eski/yeni sürüm, çok-ders ortak terim. Answerable başına 8–12 hard-negative → ≥10K çift.
**Split & leakage:** %60/20/20, **belge/ders-sürümü bazlı** (soru bazlı değil); parafraz iki split'e giremez; gizli test model eğitim-kesiminden sonra üretilen kurum-içi kaynağa öncelik; hiperparam/prompt hidden görülmeden dondurulur; her model/sürüm/tarih/decoding manifeste yazılır.
**Gold şema:** conversation/turn id · raw + gold_standalone_query · answerability · atomik claim'ler · her claim için kabul edilen span seti · kabul edilen cevap varyantları · source_id+version+kapsam · criticality · hard-negative türü · tablo header/row/col · transcript speaker/timestamp. **2 bağımsız TR annotator + adjudicator**; kritik claim uzman; answerability Krippendorff α; span token-overlap F1 + exact boundary.
**Hard-negative taksonomisi:** aynı varlık-yanlış özellik · sayı/tarih/birim · negasyon/istisna · nicelik/modalite · yan bölüm aynı terim · tablo koordinatı · transcript kimliği · sürüm çatışması · TR biçimbilim · disiplinlerarası eşadlılık · eksik multi-hop · çok-tur eski bağlam · yakın unanswerable · kaynak-içi talimat enjeksiyonu. **≥yarısı gerçek retriever confuser'ı, kalanı kontrollü adversarial** (yalnız-LLM sentetik değil).
**Deney matrisi:** A retrieval-only (BM25+n-gram, e5-large, gte-mult, TurkEmbed, BGE-M3 dense/sparse/dense+sparse/multi-vector, her dense'in BM25-RRF'i) · B rerank (yok, bge-reranker-v2-m3, TR community, jina-v2-mult, Hezarfen-HN fine-tune) · C oracle-context grounding (DeepSeek-V4-Flash Non-Think/High/Max + ≥2 TR üretici baseline) · D uçtan uca · E çok-tur & abstention · F özetleme (full-context/chunk-merge/RAPTOR-node/extract-then-abstract/RAPTOR-retrieval+raw-leaf) · G operasyonel (p50/p95, token, throughput, API maliyet, GPU/CPU/RAM, dış-servis riski). Her varyant 3 kaynak sırası + baş/orta/son konum.
**İstatistik:** eşleştirilmiş; ≥10K paired bootstrap %95 GA; McNemar; her hard-negative dilimi ayrı; seçim alt/üst GA sınırıyla; judge-kalibrasyon insanları final testten ayrı.

## 9. Kabul kapıları (öneri — ilk mühendislik hedefi, pilot sonrası dondurulur)
- **Retrieval:** answerable Recall@20 GA-alt ≥0.95 · kritik dilim ≥0.90 · multi-hop tam-set@20 ≥0.90 · nDCG@10 ≥0.85 · MRR@10 ≥0.80 · unanswerable'da kapı yanlış açılma GA-üst ≤0.05.
- **Reranker:** füzyona göre nDCG@10 ≥+0.03 (GA-alt>0) · HN pairwise ≥0.90 · sayı/negasyon/istisna pairwise ≥0.95 · hiçbir dilimde >0.02 gerileme.
- **QA/grounding/atıf:** claim support precision ≥0.95 · citation correctness ≥0.98 · citation completeness ≥0.95 · desteksiz claim ≤0.02 · **kritik desteksiz claim = 0** (≥400 kritik claim) · unanswerable abstention recall ≥0.95 · answerable yanlış-abstention ≤0.10 · partial niteleme ≥0.90.
- **Çok-tur:** rewrite varlık/kısıt koruma ≥0.95 · sonraki-tur Recall@20 ≥0.92 · ilk↔sonraki fark ≤0.05 · topic-shift sızıntı ≤0.01 · belirsizde sessiz yanlış çözüm ≤0.02.
- **Özet:** kaynak-destekli fact precision ≥0.97 · kritik çelişki=0 · gold meaning-unit coverage ≥0.85 · citation F1 ≥0.90 · normalized insight-joint ≥0.75 (insan tavanı sonrası) · konum dilimleri farkı ≤0.05 · 3-permütasyon std ≤0.03.
- Her release: ≥200 tam cevap/özet + ≥500 atomik claim **kör insan audit**.

## 10. Model karar tablosu
| Bileşen | TR kanıt | Karar |
|---|---|---|
| BGE-M3 | Doğrudan yok (B) | **Amber — benchmark adayı** |
| bge-reranker-v2-m3 | Doğrudan yok (B) | **Amber — aday** |
| TR community reranker | dar self-report (C) | yalnız yarışmacı |
| multilingual-e5-large | TR-MTEB + TR-RAG kanıtı | **Baseline zorunlu** |
| TurkEmbed4Retrieval | TR retrieval (sınırlı) | baseline/aday |
| DeepSeek-V4-Flash | TR grounding yok (D; aile B/C) | **Amber — oracle+E2E zorunlu** |
| RAPTOR | uzun-belge güçlü, düğümde halüsinasyon | routing EVET, son kanıt HAYIR |
| extract-then-abstract | uzun-özet faithfulness ile uyumlu | **ürün varsayılanı** |

**Go/no-go:** bir aday ancak gizli TR testte tüm kritik kapıları geçer + baseline'a GA-pozitif kazanç + hiçbir kritik dilimde gerileme yok + maliyet/gecikme/mahremiyet sınırında ise varsayılan olur. Ortalama accuracy, sayısal/negasyon/unanswerable dilimindeki tehlikeli hatayı telafi etmez.

## 11. Yürütme planı
- **Faz 0:** versiyonlu evidence span şeması, claim–evidence JSON sözleşmesi, answer/partial/clarify/abstain durumları, retrieval/rerank/verifier audit log.
- **Faz 1:** Hezarfen-RAG-TR-HN v1 (1.200) + 200 özet görevi (TR-EduVSum uyarlı + kurum-içi) + 2 annotator/adjudication.
- **Faz 2:** bileşen benchmark (retrieval/rerank generator'dan bağımsız; oracle-context ile DeepSeek grounding izole; TR judge kalibrasyonu).
- **Faz 3:** uçtan uca + ablation (her bileşenin katkısı; çok-tur/pozisyon/versiyon/injection stresi; kalite–maliyet Pareto).
- **Faz 4:** shadow logging + haftalık adjudication + yeni hataları HN havuzuna ekleme + kontrollü rollback.

## 12. Sonuç
Güvenilir kaynakla-konuşma = model/bağlam büyüklüğünden çok **kanıt sözleşmesi + cevaplanamazlık davranışı + ölçüm ayrıştırması** problemidir. Bu protokol uygulanmadan "BGE-M3 Türkçe'de yeterli / BGE reranker TR'yi iyi sıralıyor / DeepSeek-V4-Flash kaynağa sadık" cümlelerinin hiçbiri **literatürce doğrudan desteklenmez**.

## Kaynakça
**Çok-tur & atıf:** QReCC (NAACL21) · TopiOCQA (TACL22) · MTRAG (TACL25) · MTRAG-UN (Findings ACL26) · CORAL (2024) · ALCE (EMNLP23) · Attributed QA/AutoAIS (2022) · AttributionBench (2024) · GopherCite (2022) · RAGTruth (ACL24) · RAGAS (EACL24) · ARES (NAACL24) · RAGChecker (2024).
**Uzun belge & özet:** RAPTOR (ICLR24) · SummN (ACL22) · Context-Aware Hierarchical Merging (2025) · Faithfulness–Abstractiveness Trade-off (ACL22) · Positional Bias of Faithfulness (NAACL25) · GraphRAG (2024) · FActScore (EMNLP23) · LongDocFACTScore (LREC-COLING24) · SummHay (2024) · Stress Testing Factual Consistency (ACL26) · MiniCheck (2024).
**Türkçe & model:** M3-Embedding/BGE-M3 (Findings ACL24) + model kartı · bge-reranker-v2-m3 model kartı · TR-MTEB (Findings EMNLP25) · TurkEmbed4Retrieval (2025) · Bridging the Language Gap in RAG (2025) · RAGTurk (SIGTURK26) · DeepSeek-V4-Flash model kartı · DeepSeek-V4 (2026) · TurkBench (2026) · TR-EduVSum (SIGTURK26) · ImplicaTR (SIGTURK24).
