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
> ölçüm koşumları) — ama **köprünün yerine geçmez**. Köprü istemcisi
> (QUIC taşıması) henüz yazılmadı; `src/bridge/client.py` çerçeve kurma ve
> cevap çözme kısmını taşımadan bağımsız hazır tutuyor.

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
| geçersiz slug | tipli `invalid_school` reddi (okulun VARLIĞI backend'in kararıdır; servis okul listesi icat etmez) | `bridge/dispatch.py::Dispatcher.dispatch` |
| `Response.school` | HER cevapta (ok/err) isteğin okulu AYNEN eko edilir | `bridge/contract.py::BridgeResponse` |
| istek gövdesi | okul servis çağrısına konur; korpus anahtarı `(okul, sınıf, ders)`tir; okulsuz istek `school_required` | `service/registry.py::resolve`, `service/multi.py` |
| okuma/yazma | okul-scoped ya da hiç: damgasız satır erişilemez, sahipsiz yazma hata, aramalar tam eşitlikle süzülür | `guard/tenant.py`, `index/*`, `retrieve/*` |
| cevap cache | anahtara `school` girer (iki okul hit paylaşamaz) | `cache/response_cache.py` |

**Durum:** dağıtıcı transport-bağımsız hazır ve testli; QUIC taşıması
(`bridge/client.py`'ın ağ kısmı) henüz yazılmadı → `rag.chat` uçtan uca HİÇ
servis edilmedi (BL-010).

## 5. Bu tarafta yapılanlar (bu depoda)

| paket / dosya | ne |
|---|---|
| **`src/bridge/`** | **Üretimde koşan entegrasyon kodu.** Adı bilerek `backend` değil: bu paket backend DEĞİL, backend'e bağlanan taraftır (backend'in kendi terimi: `hab/2` = *hezarfen ai bridge*). |
| `src/bridge/contract.py` | Tel biçiminin Python karşılığı; anahtar adları **testle sabitlendi** (backend'in kendi testiyle aynı gerekçe) |
| `src/bridge/client.py` | `BridgeReader` (hab/2), `RestReader` (doğrudan HTTP), `FakeReader` (çevrimdışı) — üçü aynı `.get()` arayüzü |
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

- Köprü istemcisi (QUIC/`hab/2` taşıması) yazılmadı — `rag.chat` tel biçimi
  backend'de YAYINLANDI ama bu depodaki transport onu henüz taşımıyor.
- `rag.chat` `asker_role` gönderir (ayrı alan); bu depodaki handler rol adını
  `role` sözlüğünden bekler. Köprü istemcisi kurulunca `asker_role` → `role.role`
  eşlemesi orada yapılmalıdır (bkz. `API-CONTRACT.md` §0.2).
- **Sınıfsız korpus yönlendirilemiyor:** `registry.py`/`multi.py` korpusları
  `(str sinif, str ders)` ile anahtarlar; `(None, ders)` çifti `no_corpus`'a
  düşer (yetki katmanı `can_access` bunu desteklese bile). Kapatmak için
  korpus anahtarının sınıfsız bir sentinel kabul etmesi gerekir
  (bkz. `API-CONTRACT.md` §0.2).
- `RestReader` başkası adına okuyamaz (HTTP'de oturum sahibi kim ise o okur);
  bu bilinçli bir kısıttır, sessizce yanlış kullanıcıyı okumaktansa hata verir.
