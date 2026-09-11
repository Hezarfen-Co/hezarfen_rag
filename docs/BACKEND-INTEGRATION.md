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

### 3.2 `chat.reply` cevabı atıf taşımıyor

```rust
pub struct ChatReplyPayload { pub text: String }
```

Ürün sözümüz "her cümle kitaba dayanır, atıfa tıklayınca sayfayı bulursun".
`citations`/`abstained`/`reason` için köprüde yer yok. Bugün atıflar ancak
metnin **içinde** (`[1] s.102`) gidebilir; tıklanabilir kaynak, çekimser
ayrımı ve hayalet-atıf telemetrisi kullanıcıya **ulaşamaz**.

## 4. Önerilen sözleşme değişikliği (backend ekibine)

Geriye uyumlu, iki alan ekler; mevcut servisleri bozmaz (`#[serde(default)]`):

```rust
pub struct ChatRequestPayload {
    pub message: String,
    pub asker_role: String,
    #[serde(default)] pub history: Vec<ChatTurn>,
    /// YENİ — soruyu soranın kullanıcı kimliği. Servis bunu `on_behalf_of`
    /// olarak kullanıp öğrencinin kendi verisini okur; yetki backend'de kalır.
    #[serde(default)] pub asker: Option<String>,
}

pub struct ChatReplyPayload {
    pub text: String,
    /// YENİ — metindeki [N] işaretlerinin çözümü.
    #[serde(default)] pub citations: Vec<Citation>,
    /// YENİ — cevap üretilmedi mi ve neden.
    #[serde(default)] pub abstained: bool,
    #[serde(default)] pub reason: String,
}

pub struct Citation { pub n: u32, pub pages: Vec<i64>, pub source: String }
```

`asker` alanı yeni bir yetki yüzeyi **açmaz**: servis zaten `ApiRequest`'te
`on_behalf_of` kullanabiliyor; eksik olan tek şey kimin sorduğunu öğrenmek.

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

- Köprü istemcisi (QUIC/`hab/2` taşıması) yazılmadı.
- `asker`/`citations` sözleşme değişikliği **backend ekibinin kararı**.
- `RestReader` başkası adına okuyamaz (HTTP'de oturum sahibi kim ise o okur);
  bu bilinçli bir kısıttır, sessizce yanlış kullanıcıyı okumaktansa hata verir.
