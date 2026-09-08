# hezarfen_rag — Mock Veri

RAG geliştirme/testi için, backend'in **course-notes** verisini (AI bridge
**api-read** ile döneceği şekli) **birebir taklit eden** offline korpus. Böylece
ingestion + retrieval önce buradan yazılıp test edilir, sonra tek satırla gerçek
api-read'e geçilir.

## api-read karşılığı (gerçek sistemde)
RAG servisi veriyi HTTP'den DEĞİL, backend QUIC "hab/1" köprüsünün **api-read**
kanalından çeker (read-only, rol-gated, `on_behalf_of=<öğrenci>`):
- `GET /course-notes?course=MAT101`  → `course_notes_index.json`'daki ilgili kayıtlar
- `GET /course-notes/{id}/files/{fileId}` (blob) → `files[].path`'teki dosyanın içeriği

Yani `course_notes_index.json` = liste cevabının, `course-notes/**/*.md` = dosya
blob'unun mock'udur. Retrieval **rol/kurs kapsamlıdır**: öğrenci yalnız kayıtlı
olduğu derslerin notlarını görebilir (bkz. `courses.json` → `students`).

## Dosyalar
| Dosya | İçerik |
|---|---|
| `people.json` | Öğretmen + öğrenciler (username, role, name) |
| `courses.json` | Dersler + kayıtlar (`teacher`, `students[]`) |
| `course_notes_index.json` | course-note listesi (id, course, topic, author, `files[]`) — api-read list cevabının mock'u |
| `course-notes/<KURS>/<slug>.md` | Not içeriği (YAML frontmatter + gövde) — blob mock'u |
| `question_bank.json` | Benzer-soru üretimi + quiz için etiketli soru bankası |

## Ingestion (issue #3) beklenen akış
1. `course_notes_index.json` oku → her not için `files[].path`'i yükle.
2. Frontmatter'ı (`course`, `topic`, `author_role`) meta olarak sakla.
3. Gövdeyi chunk'la (~500-800 token, örtüşmeli); her chunk'a `{course, topic, note_id, title}` metadata ekle (rol/kurs-scoped retrieval + kaynak atıfı için).
4. Embed → vektör store (öneri: SurrealDB v3 vektör index — issue #1).
5. Retrieval'da öğrencinin `courses.json`'daki dersleriyle **filtrele**.

## Not
Bu mock TR eğitim içeriğidir ve gerçek kişisel veri içermez. Gerçek sisteme
geçişte bu dosyalar silinir; kaynak backend course-notes olur.
