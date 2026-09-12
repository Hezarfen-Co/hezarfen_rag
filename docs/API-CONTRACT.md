# API-CONTRACT.md — RAG servis endpoint sözleşmesi (backend/frontend entegrasyonu)

> Bu belge, `hezarfen_rag`'in sunduğu RAG yeteneklerinin (soru-cevap + özet)
> backend'in QUIC/HTTP endpoint'iyle nasıl tüketileceğini tanımlar. **Bu repo
> Generator/Summarizer'ı sağlar; backend bunları auth + rol-türetme + endpoint ile
> sarar.** hezarfen_backend/frontend repolarına bu repodan DOKUNULMAZ — bu yalnız
> sözleşme dokümanıdır (Ahmet/Burak entegre eder).

## 0. ALTIN KURAL — rol SUNUCU-TARAFI türetilir
`role`, kimliği doğrulanmış oturumdan (backend auth) türetilir; **ASLA istemci
header/body'sinden körü körüne alınmaz** (RES-002 §2, RES-003 §7: RagArt'ın açığı
buydu). Kasa izolasyonu (öğrenci yalnız kendi sınıf/dersini görür) bu role'e dayanır;
yanlış role = veri sızıntısı. RAG `role`'ü olduğu gibi uygular, doğrulamaz.

## 1. POST /rag/chat — kaynakla konuşma (soru-cevap)

**İstek:**
```json
{
  "query": "DNA'nın yapısı nedir?",
  "history": [                                  // opsiyonel — çok-turlu (history-aware rewrite)
    {"role": "user", "content": "DNA nasıl eşlenir?"},
    {"role": "assistant", "content": "..."}
  ],
  "role": {                                     // SUNUCU-TARAFI (auth'tan); istemciye güvenme
    "role": "student",                          // student|teacher|parent|admin
    "sinif": "12",
    "ders_list": ["biyoloji"]
  },
  "options": {"top_n": 6, "ders": "biyoloji"}   // opsiyonel
}
```

**Yanıt:**
```json
{
  "text": "DNA ... çift sarmaldır [1]. ... Watson-Crick ... [2].",
  "abstained": false,
  "reason": "",                                 // "" | guard_<kat> | insufficient_data | model_abstained
  "invalid_citations": [],                      // (#62) çözülemeyen [N] numaraları
  "citations": [
    {"n": 1, "chunk_id": "5eda...:c14", "span_ids": ["...#20.1"], "pages": [20,21], "ders": "biyoloji"},
    {"n": 2, "chunk_id": "5eda...:c10", "span_ids": ["...#17.3"], "pages": [17,18], "ders": "biyoloji"}
  ],
  "used_source_ids": ["5eda...:c14", "5eda...:c10"],
  "cost_usd": 0.00058,
  "cache_hit": false
}
```

**abstained/reason yorumu (frontend davranışı):**
- `guard_self_harm|violence_weapons|sexual_content|illegal_drugs|hate_harassment|prompt_injection`
  → `text` yaşa-uygun red mesajıdır; olduğu gibi göster (kaynak/atıf yok).
- `insufficient_data` → kaynakta yok; "Kaynaklarda bulunamadı" + yönlendirme.
- `model_abstained` → model kaynakta bulamadı.
- **`role_required`** (2026-09-11, #43) → istek rol taşımıyor ya da rol
  çözülemedi. **Fail-closed:** backend geçerli bir `role` göndermeden özet/soru
  üretilmez. Eskiden bu durumda erişim kontrolü ATLANIYORDU (SEC-02).
- **`scope_mismatch`** (2026-09-11, #42) → istemcinin gönderdiği
  `scope.sinif`/`scope.ders` sunucudaki korpusun gerçek sınıf/dersiyle
  uyuşmuyor. **İstemci kapsam etiketi bir yetki girdisi DEĞİL, yalnız eşleşme
  şartıdır** — eskiden `can_access`'e nesne olarak veriliyordu (SEC-01) ve
  9. sınıf öğrencisi `scope={"sinif":"9",...}` yazarak 12. sınıf içeriğini
  özetletebiliyordu. Backend bu alanları ya hiç göndermemeli ya da doğru
  değerle göndermelidir.
- **`payload_too_large`** (2026-09-11, #50) → HTTP **413**. Gövde
  `RAG_MAX_BODY_BYTES`'ı aştı ve **ayrıştırılmadan** reddedildi. Backend
  isteği küçültmeden tekrar denememelidir.
- **`timeout`** (2026-09-11, #50) → HTTP **504**. İstek `RAG_REQUEST_TIMEOUT_S`
  içinde bitmedi. Tekrar denenebilir (idempotent).
- **`service_unavailable`** (2026-09-11, #50) → HTTP **503**. Yakalanmamış bir
  hata oluştu. Eskiden bu durumda gövde çıplak `"Internal Server Error"` idi ve
  backend sözleşmeye göre **parse edemiyordu** (OPS-06).
- Ayrıca **401** (`X-Service-Token` eksik/yanlış, `RAG_SERVICE_TOKEN` doluysa) ve
  **429** (`Retry-After: 60` başlığıyla oran sınırı) dönebilir; bu ikisi FastAPI
  `detail` biçimindedir, gövde sözleşmesini taşımaz.
- Her cevapta **`X-Request-Id`** başlığı vardır; istemci kendi değerini
  gönderirse aynen yansıtılır (uçtan uca izleme).
- **`invalid_citations`** (2026-09-11, #62) → modelin yazdığı ama **hiçbir
  kaynağa çözülemeyen** `[N]` numaraları. Bu işaretler kullanıcıya gösterilen
  `text`'ten **kırpılmış** olarak gelir (eskiden metinde duruyor ama karşılığında
  tıklanabilir atıf kaydı olmuyordu — ACC-12). Boş liste normaldir; dolu liste
  bir kalite sinyalidir, frontend'in ayrıca göstermesi gerekmez.
  *Not (#57):* `[0,1]` gibi **çok parçalı ve aralık dışı** gruplar atıf sayılmaz
  ama hayalet de sayılmaz ve metinden kırpılmaz — onlar cümlenin içeriği
  olabilir (matematiksel aralık gösterimi).
- **`llm_unavailable`** (2026-09-12, #78) → yapay zekâ sağlayıcısına
  ulaşılamadı (429/5xx/timeout, yeniden denemeler tükendi ya da devre kesici
  açık). `text` Türkçe bir bekletme mesajıdır. **Tekrar denenebilir.** Eskiden
  bu durum HTTP 500 + `"Internal Server Error"` olarak dönüyordu ve backend
  sözleşmeye göre parse edemiyordu (OPS-06).
- **`budget_exceeded`** (2026-09-12, #79) → kullanıcı/gün ya da kurum/ay USD
  tavanı doldu. Aynı gün/ay içinde tekrar denemek işe yaramaz.
- **`scope_too_large`** (2026-09-12, #79) → istenen kapsam tek bir istekte
  yapılabilecek iş miktarını aşıyor (özet için birim ve tahmini LLM çağrısı
  tavanı). Ölçülen sömürü: `scope.pages=[1..187]` → **19 LLM çağrısı**.
  Frontend kullanıcıdan daha dar bir aralık istemelidir.
- **`service_warming_up`** (2026-09-12, #82) → servis ayakta ama boru hattı
  (PDF parse + embed + indeks) henüz kurulmadı. `/health` 200, `/ready` 503
  döner. **Kısa süreli ve tekrar denenebilir.** Eskiden bu süre boyunca hiçbir
  port dinlenmiyordu; konteyner sağlık yoklaması başarısız oluyordu.
- boş reason + abstained=false → normal cevap; `citations`'ı tıklanabilir kaynak olarak render et
  (her `[N]` → pages/span → PDF `#page=N` + highlight). **`[N]` metinde vardır; citations onu çözer.**

## 2. POST /rag/summarize — kanıtlı özet ("özet çıkar" butonu)

**İstek:**
```json
{
  "scope": {                                    // kapsam-tabanlı (soru DEĞİL)
    "pages": [16,17,18,19,20,21],               // VEYA "span_ids": [...]
    "ders": "biyoloji", "sinif": "12",
    "scope_label": "DNA'nın yapısı ve keşfi"
  },
  "role": { ... }                               // SUNUCU-TARAFI
}
```

**Yanıt:**
```json
{
  "text": "# DNA'nın Yapısı ...\n## 1. ...\n- ... [1].\n...",   // detaylı, yapılandırılmış (başlık/alt-bölüm/kalın)
  "abstained": false,
  "reason": "",                                 // "" | empty_scope
  "citations": [{"n": 1, "span_ids": ["..."], "pages": [16,17]}, ...],
  "scope_pages": [16,17,18,19,20,21],
  "hierarchical": true,                          // uzun kapsam → RAPTOR-benzeri
  "cost_usd": 0.0258
}
```

## 3. Backend'in sorumlulukları (bu repo YAPMAZ)
- **Auth + rol türetme:** oturumdan `role`/`sinif`/`ders_list` çıkar; istemciye güvenme.
- **Kaynak yükleme/indeksleme tetikleme:** öğretmen kaynak yükleyince (course-notes) ingest
  + embed + index pipeline'ını çağır (bu repo'nun `src/ingest`+`src/embed`+`src/index`);
  chunk meta'ya `{sinif, ders}` yaz (kasa izolasyonu için ZORUNLU).
- **Kalıcılık:** kalıcı Qdrant + incremental reindex (şu an in-memory; üretimde kalıcı).
- **Rate limit / DoS / maliyet tavanı** (RES-003 §7).
- **Citation → PDF görüntüleyici** (frontend): `pages`/`span_ids` → sayfa+highlight.

## 4. Notlar
- **Atıf tıklanınca ACL tekrar kontrol** (RES-003 §3): citation'a tıklayan kullanıcının
  o kaynağa erişimi hâlâ var mı (role değişmiş olabilir).
- **Maliyet:** her çağrı `cost_usd` döner; backend `costlog`/telemetriye yazabilir.
- **Servis girişi** (QUIC api-read) ve kalıcı store bu repodaki `compose.yaml`/`Containerfile`
  ile Faz 1 sonrası eklenecek — şu an Generator/Summarizer kütüphane olarak hazır.
- Kesin Python arayüzü: `src/generate/Generator.answer(query, history=, top_n=, ...)` →
  `GroundedAnswer`; `src/summarize/Summarizer.summarize(units, scope_label=)` →
  `GroundedSummary`; `src/guard/RoleContext` + `can_access`; `src/retrieve/HybridRetriever(meta=)`.
