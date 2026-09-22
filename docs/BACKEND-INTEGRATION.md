# Backend entegrasyonu — köprü sözleşmesi, boşluklar ve öneri

**Tarih:** 2026-09-11 · **Durum:** `İNSAN İNCELEMESİ BEKLİYOR`
**Kaynak:** `hezarfen_backend` (yalnız **okundu**, değiştirilmedi):
`src/ai/{protocol,chat,rag,server}.rs`, `src/web/{chatbot,course_notes,notes,classes,courses,auth}.rs`,
`src/domain/{user,role,class_group,class_member,enrollment,course,note,course_note}.rs`

## 1. Köprünün yönü — mevcut HTTP servisimiz backend'in çağırdığı şey DEĞİL

Backend QUIC **sunucusudur**; AI servisleri ona **dial eder** (`hab/2`).
Bizim `src/service/http_app.py`'imizi backend çağırmaz. Gerçek entegrasyonda
RAG servisi:

1. Backend'e bağlanır, kontrol akışında bir `Hello` yazar (yetenekler:
   `chat.reply`, `rag.index`),
2. Backend'in açtığı her akışta bir `Request{school, capability, deadline_ms,
   payload}` alır, tek `Response` yazar,
3. Okul verisini **kendisi ister**: `ApiRequest{school, path, query,
   on_behalf_of}` → `ApiResponse{status, body}`,
4. Dosya baytlarını `BlobRequest` ile ayrı akıştan alır.

> HTTP servisi yine de değerlidir (yerel geliştirme, backend-dışı entegrasyon,
> ölçüm koşumları) — ama **köprünün yerine geçmez**. Köprünün QUIC taşıması
> artık VAR: `src/bridge/transport.py` backend'e dial-out eder, `rag.chat` +
> `rag.index` ilan eder ve gelen `Request`leri `bridge/dispatch.py`'ye verir
> (§4.2). `src/bridge/client.py` ise hâlâ yalnız çerçeve kurma/çözme tarafıdır:
> backend'den BLOB okuma yolu da LANDI: `rag.index` her eki `BlobRequest` ile
> okur (2026-09-18); yalnız genel `ApiRequest` yolunun çağıranı yok (§7).

## 2. Bugün ÇALIŞAN yol: `rag.index`

`RagIndexPayload{course_note, course, author, title, content, files[]}` —
öğretmenin ders notu değiştiğinde backend arka planda gönderir. `author`
alanı sayesinde dosya baytları **o kullanıcı adına** okunabilir (`ai`
görevlisinin kendi başına erişimi yoktur). Bu yol öğrenci/öğretmen notlarını
indekslemek için yeterlidir.

**Yanıt (2026-09-17):** servis `{"files": [{"id", "doc_id"}, ...]}` döner —
`id` isteğin `RagFile.id`'siyle **aynı**, `doc_id` o ekin indeksteki korpus
kimliği. Backend `course_note_file.rag_doc_id`'yi bu eşleşmeden doldurur
(`bridge/contract.py`: `RagIndexReply`). Ayrıntı: `API-CONTRACT.md` §0.1.

## 3. İKİ BOŞLUK — kişiselleştirme ve atıf bugün köprüden geçemiyor

### 3.1 `chat.reply` isteği kimin sorduğunu taşımıyor

```rust
pub struct ChatRequestPayload {
    pub message: String,
    pub asker_role: String,   // yalnız ROL: "student" / "teacher" / ...
    pub history: Vec<ChatTurn>,
}
```

Backend'in kendi yorumu: *"the backend only forwards the role"*, *"Scoping the
answer is the service's job"*. Ama servis **hangi öğrenci** olduğunu bilmeden:

- o öğrencinin notlarını (`GET /notes`) çekemez → kişiselleştirme yok,
- sınıfını/derslerini (`/classes`, `/courses`) okuyamaz → **kasa izolasyonu
  uygulanamaz**. Yani "9. sınıf öğrencisi 12. sınıf içeriğini göremesin"
  kuralı chat yolunda **kurulamıyor**; elimizde yalnız "student" etiketi var.

Bu ikincisi bir güvenlik kuralıdır, bir özellik değil (bkz. EXP-010/SEC-01).

### 3.2 `chat.reply` cevabı atıf taşımıyor — RAG için ÇÖZÜLDÜ

`ChatReplyPayload` **hâlâ** yalnız `text` taşır; ama ürünün "atıfa tıklayınca
sayfayı bulursun" ihtiyacı artık ayrı bir yetenekle karşılanıyor: backend'in
`rag.chat` yeteneği. Tel biçiminin **otoritesi backend'in kendi belgesidir**
(`hezarfen_backend/README.md` → `## AI bridge (QUIC)` → `### The \`rag.chat\`
capability`); burada yalnız özet var:

```
RagChatRequestPayload{ message, asker, asker_role, scope:[{sinif, ders}], history }
RagChatReplyPayload{ text, abstained, reason,
                     citations:[{n, doc_id, pages, span_ids, ders}] }
```

Yani tıklanabilir kaynak (`doc_id` → `course_note_file`), çekimser/red ayrımı
(`abstained`/`reason`) ve hayalet-atıf telemetrisi rag.chat üzerinden kullanıcıya
**ulaşır**. `chat.reply` yolu değişmedi: orada atıflar yine metnin İÇİNDE gider.
Bu depodaki karşılıkları: `bridge/contract.py` `RagScopePair` (kapsam) ve
atıf sözlüğündeki `doc_id` (bkz. `API-CONTRACT.md` §0.1, §1).

## 4. Sözleşme — backend ne YAYINLADI (bu belgenin eski önerisi geçersiz)

Bu bölüm eskiden `ChatRequestPayload`/`ChatReplyPayload`'ya `asker`/`citations`
eklemeyi ÖNERİYORDU. Backend farklı bir yol seçti: atıf + kişiselleştirme
RAG'e ÖZEL yeni bir yetenekte toplandı (`rag.chat`), `chat.reply` dokunulmadan
kaldı. Yayınlanan tel biçimi (otorite: backend README `## AI bridge (QUIC)` →
`### The \`rag.chat\` capability`):

```rust
pub struct RagChatRequestPayload {
    pub message: String,
    pub asker: String,        // kullanıcı kimliği — servis `on_behalf_of` okur
    pub asker_role: String,   // student|teacher|parent|manager|admin (küçük harf)
    pub scope: Vec<RagScopePair>,   // (sinif, ders) ÇİFTLERİ — bkz. §3.2
    #[serde(default)] pub history: Vec<ChatTurn>,
}
pub struct RagChatReplyPayload {
    pub text: String,
    #[serde(default)] pub abstained: bool,
    #[serde(default)] pub reason: String,
    #[serde(default)] pub citations: Vec<RagCitation>,
}
pub struct RagScopePair { pub sinif: Option<String>, pub ders: String }
pub struct RagCitation { pub n: u32, pub doc_id: String,
                         pub pages: Vec<i64>, pub span_ids: Vec<String>,
                         pub ders: Option<String> }
```

`rag.index`'in **yanıtı** da bu haritayı tamamlar: servis her indekslediği ek
için `{"files": [{"id", "doc_id"}, ...]}` döner (`id` = isteğin `RagFile.id`'si),
backend `course_note_file.rag_doc_id`'yi bu eşleşmeden doldurur. Bu depodaki
DTO karşılıkları: `bridge/contract.py` `RagScopePair`/`RagIndexReply`.

## 4.1 Okul kapsamı (kiracılık) — telde ZORUNLU, cevapta EKO

Backend'in kendi kuralı (`src/ai/protocol.rs` → *School scoping*): filodaki her
AI servisi BÜTÜN okullara paylaşılan TEK servistir, bu yüzden okul el sıkışmada
(env/config) sabitlenemez — *"a service pinned to one school would have to be
run once per customer"*; *"there is no default and no fallback"*.

Bu depodaki uygulama (ayrıntılı tablo: `API-CONTRACT.md` §0.3):

| tel öğesi | kural | kod |
|---|---|---|
| `Request.school` | ZORUNLU. Yoksa çerçeve `malformed` — akış DÜŞER, cevap yazılmaz (geri yazılacak bir okul yok) | `bridge/contract.py::BridgeRequest.from_wire` |
| geçersiz okul belirteci | tipli `invalid_school` reddi (okulun VARLIĞI backend'in kararıdır; servis okul listesi icat etmez; filo değeri tireli uuid'dir) | `bridge/dispatch.py::Dispatcher.dispatch` |
| `Response.school` | HER cevapta (ok/err) isteğin okulu AYNEN eko edilir | `bridge/contract.py::BridgeResponse` |
| istek gövdesi | okul servis çağrısına konur; korpus anahtarı `(okul, sınıf, ders)`tir; okulsuz istek `school_required` | `service/registry.py::resolve`, `service/multi.py` |
| okuma/yazma | okul-scoped ya da hiç: damgasız satır erişilemez, sahipsiz yazma hata, aramalar tam eşitlikle süzülür | `guard/tenant.py`, `index/*`, `retrieve/*` |
| cevap cache | anahtara `school` girer (iki okul hit paylaşamaz) | `cache/response_cache.py` |

**Durum:** dağıtıcı transport-bağımsız hazır ve testli; QUIC taşıması
`src/bridge/transport.py`de LANDI (§4.2) → `rag.chat` artık telden servis
edilebilir. Eksik kalan parçalar §7'de.

## 4.2 Taşıma — `src/bridge/transport.py` (2026-09-17, BL-010 kapandı)

Backend QUIC **sunucusudur**; servis dial-out eder (`ai/protocol.rs:3-7`).
Taşıma bunu yapar:

| adım | ne | kod |
|---|---|---|
| sertifika | `GET /ai/certificate` — HER yeniden bağlanmada (backend her boot'ta yeniden üretir) | `transport.fetch_certificate` |
| el sıkışma | `Hello{protocol:"hab/2", service, capabilities, token, max_concurrent}` → `Greeting{welcome\|rejected}` | `contract.build_hello`, `BridgeTransport.register` |
| kayıt | ilan edilen yetenekler: **`rag.chat` + `rag.index`**. `chat.reply` KARŞILANIR ama İLAN EDİLMEZ — o yetenek chatbot'undur, ilan etmek sohbet trafiğini RAG'e yönlendirirdi | `transport.ADVERTISED_CAPABILITIES` |
| canlı tutma | QUIC PING her 10 s (`constant.rs:555`); uygulama düzeyinde heartbeat çerçevesi yok | `BridgeTransport.keepalive` |
| iş yönü | backend'in açtığı akışta tek `Request` → `Dispatcher.handle` → tek `Response`. Boru hattı işlemci/GPU yoğun olduğu için executor'da koşar: PING'ler durmasın | `BridgeTransport._serve_request` |
| yeniden bağlanma | üstel geri çekilme + jitter; **hiçbir hatada çıkılmaz** | `transport.run_forever` |

**Ortam (filo adları — yeni ad icat edilmedi):** `AI_BRIDGE_HOST` (varsayılan
`hezarfen_backend`) · `AI_BRIDGE_PORT` (8090) · `AI_BACKEND_URL`
(`http://hezarfen_backend:7656`) · `AI_TLS_SERVER_NAME` (`localhost`) ·
`AI_SERVICE_NAME` (`rag`) · `AI_SHARED_TOKEN` · `AI_TLS_FINGERPRINT` (boş →
TOFU: her açılışta `warn`; dolu → pinlenir, uyuşmazsa BAĞLANILMAZ) ·
`AI_MAX_CONCURRENT` (4; backend 1..=64'e kırpar) · `AI_RECONNECT_SECS` (3,0) ·
`AI_RECONNECT_MAX_SECS` (120,0) · `LOG_LEVEL`.

**Boot politikası (uygulanan):** backend yokken süreç DÜŞMEZ — loglar, bekler ve
yeniden dener; backend geldiğinde KENDİLİĞİNDEN kaydolur. Köprü uvicorn
sürecinin içinde ayrı bir arka plan thread'inde koşar
(`http_app.create_app_with_warmup` → `transport.start_in_background`), yani HTTP
yüzeyi taşımadan bağımsız çalışır. `AI_SHARED_TOKEN` yoksa da denenir: uydurma
token/varsayılan okul YOK; backend `unauthorized` der, bekleme tavana çekilir,
denemek bırakılmaz.

**Testler (ağ yok, DB yok):** `tests/unit/test_bridge_transport.py` sahte bir
QUIC sunucusuyla (`tests/unit/_fake_bridge.py`, aioquic, 127.0.0.1) kaydı,
okul eko'sunu, tipli redleri (`invalid_school`, okulsuz çerçevede cevapsız akış,
`malformed`), blob akışından ek okumayı, kopma sonrası yeniden kaydolmayı ve backend-yokken boot
politikasını koşar.

## 5. Bu tarafta yapılanlar (bu depoda)

| paket / dosya | ne |
|---|---|
| **`src/bridge/`** | **Üretimde koşan entegrasyon kodu.** Adı bilerek `backend` değil: bu paket backend DEĞİL, backend'e bağlanan taraftır (backend'in kendi terimi: `hab/2` = *hezarfen ai bridge*). |
| `src/bridge/contract.py` | Tel biçiminin Python karşılığı; anahtar adları **testle sabitlendi** (backend'in kendi testiyle aynı gerekçe). El sıkışma + çerçeveleme sabitleri de burada (`build_hello`, `parse_greeting`, `encode_frame`, `FrameStream`) |
| `src/bridge/client.py` | `BridgeReader` (hab/2), `RestReader` (doğrudan HTTP), `FakeReader` (çevrimdışı) — üçü aynı `.get()` arayüzü |
| `src/bridge/transport.py` | **QUIC taşıması**: dial-out, `Hello`/`Greeting`, gelen `Request` → `Dispatcher`, PING, üstel geri çekilmeyle yeniden bağlanma, TLS pinleme (§4.2) |
| `src/bridge/dispatch.py` | Transport-BAĞIMSIZ dağıtıcı: okul zorunlu, tipli redler, cevapta okul eko'su |
| `src/bridge/student.py` | `/users/me` + `/classes` + `/courses` + `/notes` + `/course-notes` → `StudentContext` → `RoleContext` (kasa izolasyonu) |
| `src/bridge/subject_map.py` | Backend ders başlığı ↔ korpus ders slug'ı (Türkçe İ/ı katlamalı) |
| **`src/demo/`** | **Ürün kodu DEĞİL** — örnek veri üretimi. `src/bridge`'den ayrı tutulur; karışırsa "hangi kod üretimde çalışıyor" sorusu cevapsız kalır. |
| `src/demo/scenario.py` | Tek öğrenci senaryosu (gerçek korpustan, uydurma içerik yok) |
| `src/demo/school.py` | Tam okul: şubeler, öğretmen, veli + backend yetki davranışını taklit eden `FakeSchool` |
| `src/demo/run_student.py` | Uçtan uca doğrulama koşumu |
| **`src/corpus/`** | **Korpus edinme.** `src/ingest/` ile karıştırılmamalı: orası bir PDF'i kanonik belgeye ÇEVİRİR, burası o PDF'lerin nereden GELDİĞİdir. |
| `src/corpus/eba_catalog.py` | EBA SPA bundle'ından materyal envanteri (sınıf/ders/ünite/kazanım/pdf) |
| `src/corpus/eba_download.py` | Katalogdan diske, devam ettirilebilir indirici |

### Neden `sinif` üç ayrı okumadan geliyor
Backend bu üçlüyü tek yerde tutmuyor: rol `User.role`'da, **sınıf üyesi
olunan `ClassGroup.grade`'de**, dersler `Enrollment → Course.title`'da.
Birleştirilmeden `can_access(sinif=, ders=)` kurulamaz.

## 6. Ölçülen uçtan uca sonuç (2026-09-11, 10-A / Zeynep Kaya)

| senaryo | beklenen | sonuç |
|---|---|---|
| kendi dersi (biyoloji) | İZİN | ✅ cevap, **3 atıf** (s.99, s.102, s.105 — üçü de tek sayfa) |
| kayıtlı olmadığı ders | RED | ✅ |
| başka sınıf (11) | RED | ✅ |
| rol çözülemiyor | RED | ✅ |

## 7. Açık kalemler

- **Köprü taşıması LANDI** (`src/bridge/transport.py`, 2026-09-17) — `rag.chat`
  artık telden servis edilir: kayıt, okul eko'su, tipli redler, kopma sonrası
  yeniden bağlanma ve backend-yokken boot politikası sahte bir QUIC sunucusuyla
  test edilir (`tests/unit/test_bridge_transport.py`).
- **`rag.index` SUNULUR (2026-09-18)** — gövde: `bridge/dispatch.py::_rag_index` →
  `service/notes_index.py` (not + ekler → parça → gömme → okulun not indeksi). Ek
  baytları `bridge/transport.py::read_blob` ile HAM okunur (başlık + tam `size`
  bayt). Dürüst sınır: not indeksi süreç-içidir ve not kanalı OKUL süzgeçlidir,
  kasa süzgeci değil (telde notun sınıfı/dersi yok).
  **Cevap artık metnin KENDİSİNİ de taşır (2026-09-18):** `passages` — indekslenen
  ÇOCUK parçalar (`chunk_id`, `doc_id`, `text`, `page_start`, `page_end`), yani
  "18 metin parçası" diyen panel SAYInın yanında ne çıkarıldığını da gösterebilir.
  `passages_truncated`, liste kırpıldıysa `True`'dur; `chunks` KIRPILMAZ (indekse
  yazılan toplam parça sayısı olarak kalır, `passages` uzunluğu değildir). Sözleşme:
  `API-CONTRACT.md` §0.1.
- **Backend'den genel OKUMA yolu (`ApiRequest`) QUIC üzerinden bağlanmadı.**
  `rag.chat`'in kapsamı çerçevede gelir; `rag.index` yalnız BLOB okur
  (`BlobRequest`). Çağıranı olmayan `ApiRequest` yolu yazılmadı. Öğrenci bağlamı (`BridgeReader`) gerektiren bir yetenek eklenirse
  `client.py`'ın senkron `(gönder, al)` arayüzü ile taşımanın async akışları
  arasında bir uyarlama gerekir.
- `rag.chat` `asker_role` → `role.role` eşlemesi dağıtıcıda YAPILIYOR
  (`bridge/dispatch.py::_govde`) — kapandı; taşıma yalnız çerçeveyi taşır.
- **Sınıfsız korpus yönlendirilemiyor:** `registry.py`/`multi.py` korpusları
  `(str sinif, str ders)` ile anahtarlar; `(None, ders)` çifti `no_corpus`'a
  düşer (yetki katmanı `can_access` bunu desteklese bile). Kapatmak için
  korpus anahtarının sınıfsız bir sentinel kabul etmesi gerekir
  (bkz. `API-CONTRACT.md` §0.2).
- **Kalıcı Qdrant yok (RISK-01):** indeks in-memory; yeniden başlatmada her
  korpus yeniden kurulur (#75).
- `RestReader` başkası adına okuyamaz (HTTP'de oturum sahibi kim ise o okur);
  bu bilinçli bir kısıttır, sessizce yanlış kullanıcıyı okumaktansa hata verir.
