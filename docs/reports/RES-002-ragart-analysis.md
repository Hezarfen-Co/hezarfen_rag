# RES-002 — RagArt Analizi: Ürün-Seviyesi Türkçe Eğitim RAG'i için Çıkarımlar

> Kaynak: `github.com/kadiryonak/RagArt` (Kadir'in genel-amaçlı RAG framework'ü).
> Amaç: en kaliteli yöntemleri al, eksikleri gör, öngörülebilir hataları önle.
> Aktarılabilir kararlar `docs/OPTIMIZATION.md`'ye gömüldü; bu rapor gerekçe/kanıt.
> Yöntem: repo klonlandı, 3 paralel alt-ajan (çekirdek+atıf / guardrail+eval / ürün-altyapı)
> dosya:satır düzeyinde inceledi.

## 0. Özet
RagArt olgun bir **framework** (modüler plugin, provider-agnostic, BYOK, workspace).
Güçlü: fail-closed fallback, katmanlı eval (L1-L4), hibrit+rerank, 3-katman cache,
DeepSeek + Türkçe UTF-8, incremental reindex, dürüst eval kültürü. **Ama ürün değil**:
atıf çelişkisi, rol-yetki yok, zararlı-içerik filtresi yok, canlı maliyet telemetrisi yok.
Bizim ürün (rol-bazlı, atıf-zorunlu, fail-closed, reşit-olmayan kitle) bu boşlukları kapatmalı.

## 1. ATIF (Citation) — Kadir'in 1. önceliği
**RagArt'ta nasıl gösteriliyor:** Deterministik "Kaynak Belgeler" paneli — retrieval
sırasına göre `[n]` + dosya adı + (tahmini) sayfa rozeti + snippet; tıkla → PDF `#page=N`
veya metinde substring-highlight. Panel halüsinasyon-atıf içermez (iyi).

**Kritik kusurlar (bizim kaçınacağımız):**
- **Inline `[N]` ölü kod:** UI `[N]` render ediyor ama TÜM promptlar modele kaynak etiketini YASAKLIYOR → inline atıf fiilen yok. Net çelişki.
- **"Retrieved ≠ used":** panel getirilen k kaynağı gösteriyor, cevabın gerçekten dayandığını değil → yanıltıcı atıf.
- **Groundedness yalnız uyarı, cümle-bazlı değil:** whole-answer skoru; `semantic_groundedness` cümle-bazlı sinyali hesaplayıp ATIYOR (ort. döndürüyor). Desteksiz cümle işaretlenmiyor/bloklanmıyor.
- **Sayfa no tahmini** (`item_index+1`), sayfasız formatta yanlış.

**Bizim tasarım (OPTIMIZATION.md D + A):** (a) modele numaralı bağlama `[N]` atıf ürettir + **doğrula**; (b) **cümle-bazlı** groundedness → desteksiz iddia **fail-closed blok**; (c) "kullanılan" ≠ "getirilen" ayır; (d) atıf gerçek **span metadata**'sından (span_id = `doc#sayfa.blok` + bbox — bizde ZATEN var, kanonik şema). RagArt'ın yapamadığı gerçek sayfa/bbox atfına biz hazırız.

## 2. GUARDRAIL — Kadir'in 2. önceliği (chat'te ne söyleyebilir/söyleyemez)
**RagArt'ta:** InputGuard (salt-regex prompt-injection, TR'de 8 pattern, eşik 0.5) +
GroundednessScorer (uyarı) + fail-closed fallback (dayanak yoksa LLM çağrılmaz — **güçlü**).

**Boşluklar (bizde kritik):**
- **Zararlı/toksik/PII/kendine-zarar filtresi YOK** (girdi+çıktı). Reşit-olmayan öğrenci kitlesi için kabul edilemez.
- **Rol-bazlı yetki YOK:** kaynak seçimi + genel-bilgi izni **client header**'ıyla → herhangi istemci açabilir. Authz tamamen dışarıda.
- Kapsam-dışı koruması yalnız relevance-gate (eşik 0.1, düşük).
- Injection salt-regex → parafraz/homoglyph/base64 ile atlatılır.

**Bizim tasarım:** girdi tarafı = injection + **zararlı-içerik red (yaşa uygun)** + kapsam guard + **sunucu-tarafı rol-türevli yetki** (Çelebi rol-uzay modeli: ikili ALLOW/DENY, sızıntısız, backend matris). çıktı tarafı = **cümle-bazlı groundedness blok** + zararlı-çıktı filtresi + atıf doğrulama. (OPTIMIZATION.md G.3)

## 3. Değerlendirme/Test (pass-bias YASAK)
**RagArt L1-L4:** L1 kurallar (format/dil/keyword), L2 vektör (cosine), L3 lexical
(BLEU/ROUGE saf-Python), L4 Groq-hakem (yalnız `critical`, key yoksa skip). runner +
report (baseline↔final) + ab_runner (strateji A/B, cache kapalı adil kıyas). Golden set
`edge_case` (kapsam-dışı `critical`, boş soru) + safety regresyon (`assert_not_called`).

**Al:** katmanlı maliyet-bilinçli yapı (ucuz L1-L3 kapı + pahalı hakem yalnız critical),
asla-çökmez sarmalayıcı, ayrı gösterim (otomatik≠hakem≠insan), abstain-beklenen referanslar,
safety'yi pinleyen regresyon. **Ekle:** DeepEval metrikleri (faithfulness/answer-relevancy/
contextual-precision-recall/hallucination), retrieval (recall@k/nDCG/MRR), **citation P/R**,
**güvenlik G-Eval** (kapsam-dışı/zararlı/rol-sızıntısı/fail-closed). (OPTIMIZATION.md A)

## 4. Ürün altyapısı
**Al:** 3-katman SQLite cache — **ResponseCache DeepSeek çağrısını sıfırlar** (en büyük
maliyet kazancı), EmbeddingCache amortize; incremental **content-hash reindex** (tam
rebuild'den kaçınır); stage pipeline (immutable Request + mutable State + short-circuit);
DeepSeek provider + **streaming UTF-8 pin** (Türkçe mojibake önler); **token-farkında
chunking**; request-id + p50/p95/p99 + stage timing.

**Kaçın / düzelt:**
- **Canlı token/maliyet telemetrisi YOK** — RagArt provider `usage`'ı okumuyor. Biz `costlog` ile her DeepSeek çağrısında okuruz (ayrım noktamız).
- SemanticCache **O(N) saf-Python tarama** → biz Qdrant koleksiyonu (ANN).
- `invalidate_workspace` HEPSİNİ siler; `ClassifyStage` k∈{4,5} magic-number; YAML-pipeline over-engineering (sabit liste yeter); stateless memory her istekte yeniden özet/embed.

## 5. Güncel bilgi (Kadir'in "güncel bilgiler" isteği)
RagArt **kapalı-korpus**; web/tazeleme YOK. Bizim ürün fail-closed + atıf-zorunlu olduğundan
web arama tazelik↔sadakat gerilimi taşır. Karar: **birincil = kapalı ders korpusu** (fail-closed,
kanıtlı); "güncel" = müfredat/içerik tazeleme (incremental reindex). Açıkça-güncel sorular için
**sınırlı web aracı** ileride, ayrı-etiketli (ders atfından ayrık) + guardrail'li. [KADİR ONAYI BEKLİYOR]

## 6. Agent / ReAct (Kadir'in sorusu) → OPTIMIZATION.md E
- Geliştirme-zamanı agentic sistem: EVET (Opus orkestratör + Sonnet kodcu + doğrulayıcı + Opus değerlendirici) — kuruldu.
- Üründe çalışma-zamanı: **tam ReAct HAYIR** (maliyet/gecikme/halüsinasyon; ürün fail-closed). **Sınırlı-agentic** (§0.1): kanıt yetersizse ≤2-3 tur sorgu-yeniden-yazma+retrieval, sonra çekimser. Yalnız golden-set kazancı ispatlarsa açık kalır.

## 7. Aksiyon (backlog → docs/OPTIMIZATION.md §G)
Golden set v0 → DeepEval harness → guardrail (zararlı+rol+kapsam+fail-closed) → üretim+atıf
→ cache+telemetri → 1.4/1.5 kalite ölçümü → prompt A/B → sınırlı-agentic ablation.
**Engeller:** `DEEPSEEK_API_KEY`, golden set Kadir onayı.
