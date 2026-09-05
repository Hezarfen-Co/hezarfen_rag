# RES-003 — Ürün-Seviyesi RAG Referans Mimarisi (KUZEY YILDIZI)

> **Kaynak:** Kadir (2026-09-05). Hezarfen/MedExam için hedef ürün mimarisi. Bu belge
> `docs/OPTIMIZATION.md`'nin olgun üst-kümesidir; baseline bulgularımızı (citation zayıf,
> aşırı-abstain, guardrail zayıf) doğrular ve genişletir. **Derin re-mimari maddeleri
> (EB-KOS sürümleme, layout-aware, calibration, güvenlik suite) "optimizasyon fazı"na
> ertelendi (Kadir kararı); şimdilik döngü mevcut backlog'a devam eder.**

## Özet ilke
Ürün-seviyesi RAG = "vektör DB + LLM context" DEĞİL. Asıl ürün: **bilgi tedarik hattı +
yetkili arama + kanıt seçimi + cevap doğrulama + değerlendirme + operasyon** katmanları.

**Sağlam varsayılan mimari:** Sürümlü EB-KOS + layout-aware belge işleme + yetki filtresi
altında hibrit arama + reranker + parent/child context + **kanıt yeterlilik kapısı** +
**iddia bazlı citation doğrulama** + güvenli "bilmiyorum". GraphRAG ve agentic RAG =
varsayılan DEĞİL, belirli sorgulara açılan pahalı rotalar.

**En önemli 3 prensip:**
1. **Retrieval skoru güven skoru değildir.**
2. **Citation'ın bulunması, citation'ın iddiayı desteklediği anlamına gelmez.**
3. **Daha fazla context, daha iyi cevap demek değildir.**

## Akış (offline bilgi fabrikası + online cevap hattı)
- **Offline:** Kaynak/lisans/sahip/ACL → Layout/OCR/STT/kanonikleştirme → Sürüm/veri-soyu/QC → Çocuk/ebeveyn/tablo/görsel/özet → BM25 + dense + türetilmiş indeksler.
- **Online:** Kimlik/rol/durum → Niyet/route/sorgu-yeniden-yazma → **Yetki filtreli** hibrit retrieval → Fusion/dedupe/rerank/context-packing → **Yeterlilik/çelişki/injection kontrolü** → İddia↔kanıtlı üretim → **Citation verifier/DLP/kaynaklı yanıt**.
- **Eval/trace/maliyet/canary/rollback** her iki hattı besler.

## 1. Bilgi tabanı (retrieval'dan önce başlar)
**EB-KOS varlıkları:** `SourceVersion` (değişmez sürüm), `EvidenceSpan` (gerçek kanıt: sayfa/slayt/tablo-hücresi/zaman), `KnowledgeUnit` (kanonik kavram+alias), `Relation` (kanıta bağlı kenar), `DerivedArtifact` (model üretimi özet/header), `AccessPolicy` (evidence düzeyine kadar ACL).
> Kullanıcıya gösterilen citation MUTLAKA gerçek `EvidenceSpan`'e döner; model özeti birincil kaynak gibi cite EDİLMEZ.

**Chunk metadata (asgari):** tenant/kurum/ACL; document_id/source_version_id/content-hash; ders/sınıf/kurul/konu/yıl; kaynak-türü/otorite; baskı/valid_from/valid_to/supersedes; sayfa/slayt/timestamp/bbox; dil/lisans/sahip; parser/chunker/embedding/index sürümleri; veri-soyu.

**PDF'yi düz metne indirgeme:** okuma sırası, başlık hiyerarşisi, tablo yapısı, şekil-caption, dipnot cevabın parçası. Layout-aware (Docling); parser kalitesi ayrı ölçülür (OmniDocBench). Ham dosya değişmez saklanır; header/footer/watermark ayrılır; tablo hem bütün hem satır-bazlı (hücreye satır/sütun başlığı); görsel crop+caption+paragraf+sayfa; slayt bütün+bölgesel; transkript timestamp/konuşmacı/slayt/ASR-güven; OCR/ASR belirsizi kesin kanıt sayılmaz; kaynak silinince chunk+vector+cache+özet+trace hepsi silinir.

**Chunking:** evrensel kural yok. Başlangıç: çocuk 200-450 tok (arama), ebeveyn 800-1800 tok (cevap), bölüm/kitap hiyerarşik özet, küçük overlap, modaliteye-özel. Contextual header ("bu bölüm X dersi Y konusu Z mekanizması") retrieval'i iyileştirebilir (Anthropic Contextual Retrieval: top-20 hata %5.7→%2.9→rerank %1.9 — vendor deneyi). Pahalıysa Late Chunking.

Linkler: Docling arxiv 2408.09869 · OmniDocBench 2412.07626 · Contextual Retrieval (anthropic.com/engineering/contextual-retrieval) · Late Chunking 2409.04701.

## 2. Bilgi bulma kalitesi
**Sorgu rotası (vector'e doğrudan gitme):** selam→retrieval yok; belirli PDF→parent-child/long-context; ders-içi olgusal→hibrit+rerank; sayı/öğrenci/takvim→SQL/API (RAG değil); çoklu-belge sentez→hiyerarşik; ilişki/çok-adım→KG/sınırlı-agentic; cevap yok→clarify/abstain; kişisel tıbbi→ayrı güvenlik politikası. **Long-context'i baseline olarak ölç** (bazen daha doğru ama pahalı — modele/corpus'a bağlı).

**Sorgu hazırlama:** aktif ders/belge/zamir çöz → tek-başına-anlaşılır yap → orijinali koru → orijinal+yeniden-yazılmış sonuçları birleştir → TR/Latince eşanlamlı/kısaltma genişlet → anlam değişmedi doğrula (Rewrite-Retrieve-Read 2305.14283). **TR:** şapkalı/şapkasız kaybetme; exact+normalize+char n-gram; Latince↔Türkçe anatomik sözlük; kısaltma alias sözlüğü; sayı/ilaç/gen/kod lexical ağırlık.

**Varsayılan retrieval zinciri:** ACL/tenant/sürüm/ders/tarih filtresi → BM25/sparse → dense → RRF → near-dup temizleme → cross-encoder rerank → otorite/güncellik/kapsam/çeşitlilik seçimi → parent expansion → kanıt-bütçeli context packing. BGE-M3 aday (çok-dilli dense+sparse+multi-vector) ama "TR-medikalde en iyi" denemez → gerçek sorular+hard-negative ile kıyasla (2402.03216). Eval grid: retriever başı 50/100/150 aday → 50-100'de rerank → 6/10/15 evidence → 4K/8K/12K context. `k` dinamik (RAGChecker 2408.08067).

**Context packing:** "en yüksek 10 chunk" yetmez. Amaç: tüm alt-iddiaları kapsa + tekrarı ele + kaynak çeşitliliği + otorite/güncellik + çelişen kanıtı koru + token bütçesi. **Lost-in-the-middle** (2307.03172): en güçlü kanıt başa, tamamlayıcı/karşıt sona.

## 3. Chat kalitesi
**Konuşma durumu (ham geçmiş değil, yapılandırılmış):** aktif ders/belge/konu; çözülmüş varlık/zamir; istenen cevap biçimi; önceki evidence ID'leri; açık belirsizlik; "sınava göre" vs "güncel kliniğe göre" modu. Her yeni olgusal turda retrieval yeniden değerlendirilir (körlemesine eski context = eski/yanlış kanıtı büyütür). Çok-turlu için ayrı test (mtRAG: sonraki turlarda + cevapsız sorularda zorlanma).

**Exam-truth vs clinical-truth ayrımı (MedExam kritik):** "hocanın slaytı" ≠ "atanmış kitap baskısı" ≠ "güncel kılavuz". Tek gizli authority-score ile ezme; kapsamı göster ("2025-26 kurul slaytına göre..."); çelişkiyi belirt; öğrenci notu/model özeti onaylı kaynağı sessizce geçersiz kılmaz.

**Citation deneyimi (2 metrik):** citation **recall** (önemli iddiaların hepsi kaynaklı mı) + citation **precision/entailment** (gösterilen kaynak iddiayı gerçekten destekliyor mu) — ALCE ayrı değerlendirir (2023.emnlp-main.398). Üretimde: her iddia `evidence_id` taşır; model YALNIZ verilen ID'leri kullanır; URL/sayfa'yı model üretmez, backend ID'den çözer; citation tıklanınca ACL tekrar; kullanıcı tam sayfa/slayt/timestamp+highlight görür; "kaynak var ama iddia desteklenmiyor" → cevap GEÇMEZ.

**İki aşamalı hallucination guard:**
- **Üretim öncesi (evidence sufficiency):** soru corpus kapsamında mı; alt-iddiaların kaçı kanıtlı; güncellik/otorite; çelişki/eksik → `supported`/`partially_supported`/`not_found`.
- **Üretim sonrası (claim verifier):** cevabı atomik iddiaya ayır → her iddiayı citation'la eşle → entailment+coverage → desteksiz cümleyi sil/yeniden-üret/çekimser → dil/PII/güvenlik.
- Streaming yapılacaksa evidence-sufficiency SONRASI başla (son doğrulama başarısız olabilecek cevabı stream etme).

## 4. Hangi gelişmiş RAG ne zaman
| Mimari | Yer | Bedel |
|---|---|---|
| Hibrit+reranker | genel olgusal (VARSAYILAN) | dengeli |
| Long-context | tek belge/bölüm seçili | yüksek input + ortada-kaybolma |
| Hiyerarşik/RAPTOR (2401.18059) | kitap özeti/bölüm-karşılaştırma/üst-düzey | özet üretim/güncelleme |
| Layout/multimodal | slayt/tablo/anatomi görseli | parsing+multimodal doğrulama |
| KG/GraphRAG (2404.16130) | ilişki/önkoşul/corpus-teması (global) | graph+sürüm+poisoning yüzeyi |
| Corrective/agentic (CRAG 2401.15884) | çok-adım/ilk-retrieval yetersiz | gecikme+maliyet+nondeterminism |
| Federated | ayrı kurum/sistem | kimlik+birleştirme |

Adaptive-RAG (2403.14403): retrieval-yok / tek-aşama / iteratif arası router. CRAG fallback kapalı-corpus'ta kontrolsüz web DEĞİL → "onaylı dış kaynak" veya açık `not_found`.

## 5. Güven skoru
Kullanıcıya cosine gösterme (sorgular arası kıyaslanamaz; otorite/kapsam/doğru-kullanım ölçmez). Gösterilecek skor: "benzer skorlu geçmiş cevapların yüzde kaçı uzman etiketine göre tüm iddiaları yeterli kanıtla destekledi?". Girdiler: answerability, reranker skoru+1-2 farkı, claim coverage, citation entailment, bağımsız kaynak sayısı, authority/freshness, çelişki, evidence çeşitliliği, parser/OCR güveni. **Platt/isotonic calibration**, ECE+Brier izle. Kullanıcıya tek sayı yerine: **Kanıt güçlü / Kanıt sınırlı / Kaynakta bulunamadı**. "Kaynak otoritesi", "kanıt yeterliliği", "cevap güveni" AYRI alanlar.

## 6. Maliyet ve gecikme
`C_ay = C_ingestion + N_q(C_route+C_search+C_rerank+C_LLM+C_verify) + C_storage,eval,ops`. Gizli maliyet: OCR/ASR/multimodal parsing, contextual header/summary, embedding/chunker değişince tam reindex, graph, LLM-judge eval, insan etiketleme, trace/log, silme yayılımı. **İş metriği: istek başı değil, başarılı+kanıtlı çözülen soru başı maliyet.** Optimizasyon sırası: ucuz route → dinamik context bütçesi → dedup → küçük model rewrite/rerank + güçlü generator → exact/retrieval/prompt-KV cache → cache anahtarına tenant+ACL-hash+corpus-sürüm+retriever+prompt → **izinleri farklı kullanıcılar arası semantic cache PAYLAŞMA** → batch offline embedding → agent-loop/tool/output sınırı → eski indeks/embedding kaldır. **RTX 4060 8GB:** embedding/rerank/batch-index yerel OK; embedding+rerank+büyük-generator yüksek-concurrency birlikte kapasite testi ister → başlangıçta generator API'de, embed/rerank yerelde. SLO başlangıç: standart rotada p95 ilk-token ~2.5s, tam cevap ~8-10s; agentic ayrı+gevşek SLO.

## 7. Güvenlik (tehdit → kontrol)
Tenant sızıntısı→retrieval-öncesi ACL/ABAC+shard/namespace+row-level+**fail-closed**; indirect injection→kaynağı güvenilmeyen-veri işaretle+gizli-metin tara+sanitize+role-ayrım+tool'u generator'dan ayır; corpus poisoning→allowlist+imza/hash+dört-göz+provenance+düşük-güven tier; eski kaynak→sürüm/validity/tombstone/anında-engel; embedding sızıntısı→şifreleme+least-privilege+vector-store'u istemciye açma+network-isolation; PII/sağlık→minimizasyon/redaction/kısa-retention/silme-zinciri; zararlı dosya→sandbox-parser+MIME+limit+malware/zip-bomb; cache sızıntısı→tenant+ACL+corpus-sürümlü key+hassas-sorguda cache-kapat; tool suistimali→policy-proxy+allowlist+şemalı-param+least-privilege+insan-onay; DoS/maliyet→rate/token/iteration limit+kuyruk+circuit-breaker; supply-chain→pin+hash+SBOM+lisans; log sızıntısı→ham-prompt/kaynak loglama+redaction.

Referans: OWASP LLM08 Vector/Embedding Weaknesses; Microsoft Spotlighting (injection provenance); KG-RAG poisoning 2507.08862; NIST AI 600-1 GenAI profili.

**MedExam hukuk/veri:** ders materyali lisansı net; öğrenci sağlık soruları özel-nitelikli veri (KVKK) → loglama/retention buna göre; AB AI Act Annex III (eğitim, intended-purpose'a göre); öğrenci profili+adaptif veri evidence-corpus'tan FİZİKSEL+MANTIKSAL ayrı.

## 8. Kaliteyi ölçme
**3 testi ayır:** retrieval-only (altın evidence bulunuyor mu) · oracle-context generation (altın evidence verilince doğru mu) · end-to-end. Böylece hata parser/retriever mı generator mı belli olur.

**Başlangıç release kapıları (MedExam önerisi):** yayınlanan chunk'larda source/version/ACL/locator/hash %100; Evidence Recall@50 ≥0.95 (kritik tıbbi ≥0.99); rerank-sonrası coverage@10 ≥0.90; faithfulness ≥0.90; citation recall ≥0.95; citation precision/entailment ≥0.95; cevapsız-tespit recall ≥0.95; kanıtsız-ama-emin ≤%1; TR uygunluk 1.00; cross-tenant/ACL 1.00 (sıfır sızıntı); injection sıfır-açık; judge-uzman κ≥0.75; latency/maliyet p95-bütçe.

**Cohort kırılımı:** ders (anatomi/fizyoloji/patoloji...); kaynak-türü (kitap/slayt/transkript/not); dil (TR/Latince/kısaltma); soru-türü (doğrudan/sentez/multi-hop/tablo-görsel); cevapsız/belirsiz/çelişkili; sürüm; yüksek-risk; kurum/yetki.

**Eval seti:** 300-500 (günlük) + 1000+ dondurulmuş (release). Her soru: kabul-cevaplar+atomik-iddialar+geçerli evidence span(lar)+answerability+risk+sürüm. Dağılım: %25 doğrudan, %15 eşanlamlı/varyant, %15 çoklu-belge, %10 multi-hop, %10 tablo/görsel/transkript, %10 çok-turlu, %10 cevapsız/belirsiz/çelişkili, %5 injection/ACL/sızıntı. **Hard-negative** kritik: aynı-terim-yanlış-organ, aynı-konu-yanlış-ders/baskı, eski-kılavuz, near-dup-kritik-kelime-farklı, cevap-var-erişim-yok, tablo-doğru-yanlış-sütun, öğrenci-notu-onaylı-kaynakla-çelişik.

RAGAS/DeepEval hızlı regression sinyali; **LLM judge tek başına release otoritesi DEĞİL** (positional bias — A/B ters çevir, judge pinle, anlaşmazlığı uzmana; 2024.acl-long.511).

## 9. Operasyon ve gözlemlenebilirlik
**Yeniden-oynatılabilir trace (her cevap):** orijinal+yeniden-yazılmış sorgu; erişim-kapsamı hash (kimlik değil); filtreler; aday chunk ID+skor; fusion/rerank; context'e giren evidence ID+sıra; corpus/index/prompt/model/verifier sürümleri; token/maliyet/aşama-latency; iddia+citation eşleşme; abstention/conflict/safety kararı. Ham hassas içerik loglanmaz.

**Üretim:** idempotent indeksleme; başarısız belge dead-letter; yeni embedding/chunk mavi-yeşil; golden geçmeden alias değişmez; canary+shadow; hızlı rollback; yetki değişimi query-katmanında anında (reindex bekleme); silme-SLA+backup-restore testi; reranker/embedding drift izle; citation-hata/`not_found`/conflict/düşük-güven/cache-hit/source-dağılımı alarm.

**Geri bildirim (👍/👎 yetmez):** yanlış-kaynak / kaynak-doğru-cevap-yanlış / eksik / eski / citation-açılmıyor / gereksiz-uzun / kaynakta-yoktu / güvenlik. Onaylanan → regression setine aday.

## 10. Hezarfen somut başlangıç reçetesi + öncelik
**Reçete:** Postgres-benzeri kanonik metadata/ACL + object storage; layout-aware parser+modalite-extractor; EvidenceSpan-tabanlı parent-child indeks; BM25+BGE-M3 dense; RRF; bge-reranker-v2-m3 aday; 80-120 aday→50-80 rerank→8-12 evidence; dinamik 4K-8K context; search-relevance ve source-authority AYRI skor; üretim-öncesi evidence-sufficiency; yapılandırılmış `claims[]+evidence_ids[]+conflicts[]`; üretim-sonrası claim/citation verifier; `supported/limited/not_found`; seçili-belgede long-context fallback; kitap-özetinde sonra RAPTOR; GraphRAG yalnız query-log ilişkisel-ihtiyaç kanıtlarsa; agentic ≤birkaç iterasyon bütçe/süre-sınırlı; öğrenci-profili/adaptif/corpus AYRI servis.

**Öncelik sırası:** 1) golden eval + trace altyapısı · 2) sürüm/ACL/provenance · 3) layout parsing + evidence locator · 4) hibrit + reranker · 5) abstention + claim-level citation · 6) multi-turn chat state · 7) cache/maliyet/latency · 8) multimodal · 9) adaptive routing · 10) (kanıtlanırsa) GraphRAG/agentic.

---
**Bizim durumumuz (2026-09-05) bu referansa göre:** ✅ #4 (hibrit+reranker), kısmen #1 (eval harness+trace/costlog var, golden set TASLAK), kısmen #5 (üretim+atıf+fail-closed var AMA claim-verifier/evidence-sufficiency-kapısı YOK → baseline'daki citation-zayıf + aşırı-abstain bunun eksikliği). Eksik: #2 sürüm/ACL, #3 layout, #6 multi-turn, #7 cache-kısmen, #8-10. Sıradaki döngü backlog: bkz `docs/OPTIMIZATION.md §G/§H` (P0: atıf/claim-verifier, aşırı-abstain/evidence-sufficiency, guardrail LLM-sınıflandırıcı).
