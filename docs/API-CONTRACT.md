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

### 0.1 İki tel-biçimi kararı (2026-09-17)

**`rag.index` yanıtı bir dosya eşleşmesi taşır.** Servis,
`{"files": [{"id": ..., "doc_id": ...}, ...]}` döner. `id` isteğin `RagFile.id`'siyle
**aynı** değerdir; `doc_id` o ekin indekste kazandığı korpus kimliğidir. Neden:
backend `course_note_file.rag_doc_id`'yi yalnız bu eşleşmeden öğrenir — bir eki
yeniden indekslerken/silerken hangi korpusu hedefleyeceğini bilmeli (`bridge/contract.py`:
`RagIndexReply`/`RagIndexReplyFile`).

**`rag.chat` kapsamı (sınıf, ders) ÇİFT listesidir.** Eski `role.sinif` +
`role.ders_list` biçimi bir KARTEZYEN ÇARPIM ifade eder (`sinif="10"` +
`ders_list=["biyoloji","satranç"]` → "10-biyoloji **VE** 10-satranç"); oysa gerçek
kapsam "10-biyoloji **VEYA** okul-satranç" olabilir ve düzleştirme yanlış bir
(sınıf,ders) grant'i açar. Çift listesi her grant'i tek tek taşır; `sinif` boş/None
= sınıfa bağlı olmayan korpus (okul kulübü/etüt). Eski biçim **geriye uyumlu**
çalışmaya devam eder, ancak `scope` çift listesi VERİLİRSE o tercih edilir
(`bridge/contract.py`: `RagScopePair`; `guard/roles.can_access`).

### 0.2 Bilinen açıklar (2026-09-17; (a) kapandı, (b) açık)

**(a) `asker_role` → `role` eşlemesi — ÇÖZÜLDÜ (2026-09-17; taşıma da landı).**
Backend `rag.chat`'te soranın rolünü AYRI bir `asker_role` alanında gönderir
(`RagChatRequestPayload`). Eşleme artık transport-bağımsız dağıtıcıda YAPILIR:
`bridge/dispatch.py::Dispatcher._govde` her iki yetenek için de
`{"role": {"role": asker_role}}` üretir (`role` yoksa servis zaten
`role_required` ile fail-closed reddeder). Çerçeveyi taşıyan QUIC istemcisi de
yazıldı (`bridge/transport.py`, 2026-09-17) — bu madde TAMAMEN kapandı.

**(b) Sınıfsız korpus yönlendirilemiyor.** `scope` çiftindeki `sinif` boş/None
olabilir (okul kulübü/etüt) ve yetki katmanı bunu destekler
(`can_access` tam-çift eşleşmesi). ANCAK yönlendirme katmanı korpusları hâlâ
`(str sinif, str ders)` ile anahtarlar (`src/service/registry.py`,
`src/service/multi.py`); `(None, ders)` çifti bu yüzden **`no_corpus`** döner.
Kapatmak için korpus anahtarının sınıfsız bir sentinel (`\"\"` ya da ayrı bir
anahtar alanı) kabul etmesi ve `book_path`/keşif mantığının sınıfsız dizini
bulması gerekir — bu wave'de YAPILMADI.

### 0.3 Okul kapsamı (kiracılık) — OKUL İSTEKLE gelir, hiçbir env onu seçmez

**Tek kural: okulla kapsanmış ya da hiç.** Filo tek servistir ve BÜTÜN okullara
hizmet eder; bir okula sabitlenmiş bir servis "her müşteri için bir kez
çalıştırılmak" zorunda kalırdı (backend `src/ai/protocol.rs` → *School scoping*:
*"there is no default and no fallback"*). Bu depodaki tek ifadesi
`src/guard/tenant.py`.

| katman | kural | yer |
|---|---|---|
| Tel çerçevesi | `Request.school` ZORUNLU; yoksa `malformed` (akış düşer, cevap yazılmaz); geçersiz slug → tipli `invalid_school`; **her** `Response` okulu AYNEN eko eder | `bridge/contract.py` (`BridgeRequest.from_wire`, `BridgeResponse`), `bridge/dispatch.py` |
| İçerik | Damgasız (okulsuz) satır ERİŞİLEMEZ — "paylaşılan/public" bir boyut YOKTUR; eski satırlar taşınmaz, kaynaktan yeniden indekslenir (VPS verisi tek kullanımlık) | `guard/tenant.py`: `content_visible`, `visible_owners`, `require_owner` |
| Korpus anahtarı | `(okul, sınıf, ders)` — iki okulun aynı dersi birbirini EZEMEZ; okulsuz istek `school_required`, geçersiz okul `unknown_school` | `service/registry.py::CorpusKey` + `resolve` |
| Korpus keşfi | `RAG_CORPORA` OKUL ADI TAŞIMAZ (yalnız ders süzgeci); korpuslar diskten `data/<okul>/<kasa>/<sınıf>/<ders>/kitap.pdf` ile keşfedilir | `service/multi.py` (`school_from_book_path`, `discover_tenants_`) |
| Yazma | Yeni yazmada `require_owner` ZORUNLU; sahipsiz yazma bir HATA, "paylaşılan satır" değil | `guard/tenant.py`, `build_service(school=...)` (varsayılanı yok) |
| Store okuma | Dense payload + BM25/sparse satır damgası zorunlu; aramalar okur okuluna **tam eşitlikle süzülür** (kırpma değil süzgeç) | `index/dense.py`, `index/lexical.py`, `retrieve/sparse.py`, `retrieve/hybrid.py` |
| Cevap cache | Cache anahtarına `school` girer — iki okul aynı soruda hit PAYLAŞAMAZ | `cache/response_cache.py` |
| HTTP yüzeyi | Gövdelerde `school` alanı vardır; üretimde onu BACKEND doldurur (servis backend'in arkasındadır). Okulsuz HTTP isteği de `school_required` ile reddedilir | `service/http_app.py` (`ChatRequest.school`) |

**Tel biçiminde tipli okul redleri:** `malformed` (okul alanı yok — çerçeve
düzeyi), `invalid_school` (slug biçimi geçersiz), `school_required` (istek
okulsuz), `unknown_school` (okul çözülemedi/ayrılmış). Dördü de fail-closed'dır;
hiçbiri "varsayılan okul"a düşmez, hiçbiri başka okulun satırını döndürmez.

**Neden "paylaşılan müfredat" yok:** bir kez var olan bir `public` boyutu,
damgasız eski satırların taşınması demek olurdu; o da "sahibi belirsiz içerik"
sınıfını geri getirirdi. Yerine: her korpusun bir okulu vardır (`require_owner`),
okulsuz okur hiçbir şey görmez.

**Köprüde durum:** dağıtıcı (`bridge/dispatch.py`) transport-BAĞIMSIZ hazır ve
testlidir (okul eko'su, yetenek eşlemesi, `asker_role` → `role`). QUIC taşıması
(`bridge/transport.py`) 2026-09-17'de eklendi: dial-out + kayıt + gelen
`Request`lerin dağıtıcıya verilmesi + yeniden bağlanma. `rag.chat` böylece
telden servis edilebilir; `rag.index` de SUNULUR (2026-09-18) — ek baytları
`BlobRequest` ile okunur, cevap `{course_note, chunks, files[], failed[], summary}`.
HTTP yüzeyi yerel koşum/ölçüm için durur; backend onu ÇAĞIRMAZ.

## 0. Sorumluluk sınırı — kim neyi yapar (#87, 2026-09-12)

Denetimde (OPS-16) şu tespit edildi: bu sözleşme backend'e *"kaynak yükleme/
indeksleme tetikleme"*, *"kalıcılık"*, *"rate limit / maliyet tavanı"* diyordu
ama **RAG deposu bunları yapacak arayüzü sunmuyordu** → iki ekip birbirini
bekliyordu. Sınır şöyle netleştirildi:

| iş | kim | bu depoda durum |
|---|---|---|
| Kaynağın sahipliği, yetkisi, yaşam döngüsü (oluştur/sil) | **backend** | — |
| Chunk + vektör + sparse indeksin kurulması | **RAG** | var (`build_service`) |
| **Kaynak silme → chunk/vektör/cache kaskadı** | **RAG** | var (`src/corpus/deletion.py`, #76) |
| Kaynak sürümü → cache geçersizleştirme | **RAG** | var (`corpus_version`, #77) |
| Oran sınırı (kullanıcı bazlı) | **backend** | RAG'da ikinci katman var (#50) |
| Maliyet tavanı (kullanıcı/kurum) | **her ikisi** | RAG'da var (#79) |
| Atıf tıklanınca ACL yeniden kontrolü | **backend** | RAG kaynak kimliğini döndürür |
| Çok-turlu rewrite | **RAG** | **artık bağlı** (#87/OPS-14) |

**Not (OPS-14):** `history` alanı sözleşmede duruyordu ama `build_service` hiç
`rewriter` geçirmediği için üretimde **sessizce atılıyordu**. Bağlandı;
`RAG_REWRITE_HISTORY=0` ile kapatılabilir (geçmişli her soruda bir ek LLM
çağrısı, ~$0,0002).

**Henüz yok:** `POST /rag/ingest` ve `DELETE /rag/sources/{id}` HTTP uçları.
Silme/indeksleme mantığı hazır (`src/corpus/deletion.py`) ama HTTP yüzeyi
köprü sözleşmesine bağlı (#95) — backend RAG'ı QUIC köprüsüyle çağırıyor,
HTTP ile değil. Köprü yeteneği tanımlanınca eklenecek.

## 1. POST /rag/chat — kaynakla konuşma (soru-cevap)

**İstek:**
```json
{
  "query": "DNA'nın yapısı nedir?",
  "school": "ataturk-anadolu-lisesi",            // KİRACI: zorunlu (bkz. §0.3). Okulsuz istek school_required ile REDDEDİLİR.
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
    {"n": 1, "chunk_id": "5eda...:c14", "span_ids": ["...#20.1"], "pages": [20,21], "ders": "biyoloji", "doc_id": "5eda1f0a9c32"},
    {"n": 2, "chunk_id": "5eda...:c10", "span_ids": ["...#17.3"], "pages": [17,18], "ders": "biyoloji", "doc_id": "5eda1f0a9c32"}
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
  **Kurum = OKUL'dur** (`RAG_TENANT_MONTHLY_USD`): sayaç okul anahtarına yazılır
  ve okul başına ayrıdır (bir okulun harcaması başka okulun tavanını yemez).
  Okulsuz istekte yalnız kullanıcı tavanı işler (bkz. §0.3).
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
  "school": "ataturk-anadolu-lisesi",           // KİRACI (bkz. §0.3)
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
- **OKULU TAŞIMA (kiracılık):** her isteğe `school` (okul slug'ı) koy — hem HTTP
  gövdesine hem hab/2 çerçevesine. Servis okul uydurmaz, env'den okul seçmez;
  okulsuz istek `school_required` ile reddedilir (bkz. §0.3).
- **Kaynak yükleme/indeksleme tetikleme:** öğretmen kaynak yükleyince (course-notes) ingest
  + embed + index pipeline'ını çağır (bu repo'nun `src/ingest`+`src/embed`+`src/index`);
  chunk meta'ya `{school, sinif, ders}` yaz (kasa izolasyonu + kiracılık için ZORUNLU;
  okulsuz satır hiçbir okura görünmez — §0.3).
- **Kalıcılık:** kalıcı Qdrant + incremental reindex (şu an in-memory; üretimde kalıcı).
- **Rate limit / DoS / maliyet tavanı** (RES-003 §7).
- **Citation → PDF görüntüleyici** (frontend): `pages`/`span_ids` → sayfa+highlight.

## 4. Notlar
- **Atıf tıklanınca ACL tekrar kontrol** (RES-003 §3): citation'a tıklayan kullanıcının
  o kaynağa erişimi hâlâ var mı (role değişmiş olabilir).
- **Maliyet:** her çağrı `cost_usd` döner; backend `costlog`/telemetriye yazabilir.
- **Servis girişi:** HTTP servisi bu repoda VAR (`src/service/http_app.py` +
  `compose.yaml` + `Containerfile` + systemd unit + CI deploy); backend onu
  ÇAĞIRMAZ — gerçek entegrasyon QUIC/`hab/2` köprüsüdür ve taşıması
  `src/bridge/transport.py` ile LANDI (2026-09-17, BL-010 kapandı). `rag.chat`
  artık telden servis edilir; HTTP yüzeyi yerel koşum/ölçüm için durur.
- Kesin Python arayüzü: `src/generate/Generator.answer(query, history=, top_n=, ...)` →
  `GroundedAnswer`; `src/summarize/Summarizer.summarize(units, scope_label=)` →
  `GroundedSummary`; `src/guard/RoleContext` + `can_access`; `src/retrieve/HybridRetriever(meta=)`.
