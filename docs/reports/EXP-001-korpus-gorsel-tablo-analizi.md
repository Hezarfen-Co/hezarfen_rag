# EXP-001 — Korpus Görsel/Tablo/Diyagram Yoğunluk Analizi

> **Tür:** ANALİZ / ÖLÇÜM (model deneyi DEĞİL — LLM çalıştırılmadı).
> **Nihai durum:** `İNSAN İNCELEMESİ BEKLİYOR`
> **Tarih:** 2026-08-31 · İlgili: [[bulgular]] · [[benchmark]] · [[plan]] (Faz 0.3c/0.3d)

## 1. Amaç
Korpusun görsel/tablo/diyagram yoğunluğunu **ölçmek** → hangi sayfa/içerik pahalı
VLM'e (DeepSeek-vision), hangisi ucuz metne gitmeli; RAG'i doğru beslemek + LLM'i
verimli kullanmak. (Kaynak: [[Literatür/Hezarfen]] "PDF'yi gerçekten anlama".)

## 2. Değiştirilen unsur
Yok (bu bir A/B model karşılaştırması değil). Ölçüm yöntemi kuruldu:
görsel kaplama = **union (grid)** — alan-toplamı değil (üst üste binmeyi saymaz);
tablo = pdfplumber + **sıkı kalite filtresi** (dolu-oran ≥ %60).

## 3. Ayarlar / ortam / sürümler
| Alan | Değer |
|---|---|
| Kod (modül) | `hezarfen_rag/src/ingest/visuals.py`, `tables.py`, `pdf_parse.py` |
| Kod deposu commit | 0.3d: `9375f60` · 0.3c: `5e9fe36` · HEAD: `4924a2a` |
| Kütüphane | PyMuPDF 1.27.2.3, pdfplumber (0.11) |
| Ortam | Windows 11, Python 3.11.0 |
| Model / prompt sürümü | **YOK** (LLM çağrısı yapılmadı) |
| Veri kümesi sürümü | `data/` (indirilen MEB/EBA); analiz: 12-bio (187s) + 6 ders örneklemi |
| Golden set | Kullanılmadı (analiz, QA değil) |

## 4. Başlangıç ↔ Yeni karşılaştırma (aynı koşul)
**N/A** — bu bir model deneyi değil; "başlangıç sistemi" (baseline) ile
karşılaştırılacak bir "yeni sistem" çıktısı yok. İlk baseline↔yeni karşılaştırması
Faz 1 (text-RAG) EXP-002'de yapılacak.

## 5. Otomatik metrikler (gerçek ölçüm — [DENEYSEL SONUÇ])
**12-bio (187 sayfa):** figür-ağırlıklı (görsel≥%40) = **50 sayfa (%27)** · karma
(%10–40) = 94 (%50) · salt-metin (<%10) = 43 (%23) · ort. görsel kaplama %30 ·
medyan görsel-parça/sayfa 14 (max 3251).
**Cross-ders (figür-ağırlıklı % / ort. görsel / medyan parça):**
| Ders | Figür-ağırlıklı | Ort. görsel | Medyan parça |
|---|---|---|---|
| 12 biyoloji | %27 | %30 | 14 |
| 12 fizik | %15 | %19 | 5 |
| 12 kimya | %5 | %16 | 4 |
| 12 matematik | %42 | %34 | 2 |
| 8 fen | %41 | %35 | 13 |
| 8 matematik | %35 | %32 | 4 |

**Tablo (12-bio):** ham `find_tables` 270 → filtre (dolu≥%60) sonrası az sayıda
gerçek tablo; sayfa 20 DNA/RNA tablosu (%100 dolu) tutuldu, sayfa 1/12 dekoratif
kutu elendi.

## 6. LLM-hakem sonuçları
**N/A** — LLM-hakem çalıştırılmadı.

## 7. İnceleme için örnekler (Kadir)
| Tür | Örnek | Not |
|---|---|---|
| Dikkat çeken | 12-bio s.13 (max ~3251 parça) | vektör-kompozit diyagram; embedded çekilemez → bölge render |
| Doğru filtre | 12-bio s.20 (5x2, %100) | gerçek DNA/RNA tablosu tutuldu |
| Doğru eleme | 12-bio s.1 (kapak), s.12 (ikon kutusu %50) | dekoratif → elendi |
| Uç değer | 12 kimya (%5 figür) ↔ 12 matematik (%42) | ders bazlı varsayım olamaz → sayfa-bazlı yönlendirme |
> Başarılı/başarısız/sınırda "model çıktısı" örneği **N/A** (model yok). Yukarıdakiler ölçüm örnekleridir.

## 8. Ham çıktı / log yolları
- Bulgular özeti: `C:/Users/w/Documents/Hezarfen/rag/bulgular.md`
- Üreten kod: `hezarfen_rag/src/ingest/{visuals,tables,pdf_parse}.py`
- Testler: `hezarfen_rag/tests/{unit,integration}/test_{visuals,tables,pdf_parse}.py`
- **Not (dürüstlük):** Ölçüm ad-hoc script + testlerle üretildi; kalıcı ham-çıktı dosyası (JSON dump) **saklanmadı**. Tekrar üretim: `analyze_document()` / `extract_tables()` çağrısı. → İyileştirme önerisi Backlog'da.

## 9. Gecikme / token / donanım / maliyet
| Alan | Değer |
|---|---|
| LLM token | 0 (çağrı yok) |
| **Maliyet** | **$0.00** (LLM kullanılmadı; `Maliyet.md`'ye run eklenmedi) |
| Gecikme | `analyze_document(12-bio)` ~ integration testinde ~36 sn (187 sayfa parse) |
| Donanım | yerel CPU (PyMuPDF/pdfplumber); GPU yok |

## 10. Nihai durum
`İNSAN İNCELEMESİ BEKLİYOR` — Kadir onayı olmadan bulgular "kesin" sayılmaz,
`COMPLETED.md`'ye taşınmaz. (bulgular.md'deki değerler kod+testle doğrulanmıştır ama
nihai kabul Kadir'de.)
