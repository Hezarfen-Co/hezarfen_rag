# EXP-003 — Faz 0.8: OCR fallback + özet-PDF uçtan uca

- **Tarih:** 2026-09-06
- **Commit (kod):** `5d03c07` (OCR feature)
- **Ortam:** Windows 11, Tesseract-OCR 5.x (`C:\Program Files\Tesseract-OCR`, eng+osd kurulu), Türkçe dil verisi proje-yerel `models/tessdata/tur.traineddata` (7.4MB, git-ignore), `pytesseract` (venv), Pillow, PyMuPDF.
- **Ham çıktı:** `scratchpad/exp003_ocr_diag.py` (tanı), `exp003_ocr_debug.py` (teşhis), `exp003_ocrA.py` (OCR kanıt), `exp003_demo.py` (özet-PDF).
- **İlke:** pass-bias YOK — OCR'ın NE yapıp NE yapamadığı dürüstçe.

## 1. OCR ihtiyacı — tanı (neden fallback, neden default-off)
`parse_pdf` yalnız text-layer okur; taranmış/görüntü-sayfa SESSİZCE indekse/özete girmez. 16 kitaplık örneklem (3072 sayfa):

| Bulgu | Değer |
|---|---|
| OCR-adayı sayfa (text-layer<20 kar + görüntü) | **34 / 3072 = %1.1** |
| Çekirdek akademik kitaplar (bio/kimya/fizik/tarih/edebiyat) | ~%99 `text_ok` (2000+ kar/sayfa) |
| OCR-ağır tek kitap | ortaokul/8 görsel-sanatlar (160 sayfa, yalnız 26 `text_ok`, 15 OCR-adayı, 52 boş) |

→ OCR **hedefli fallback**; text-layer'lı %99 için tesseract bağımlılığı gereksiz → `parse_pdf(ocr=False)` **varsayılan KAPALI**.

## 2. OCR doğruluğu (fix sonrası)
`ocr_available('tur')` = True. Bilinen text-layer'lı bio sayfasında text-layer ↔ OCR:

| | metin |
|---|---|
| text-layer (868 kar) | `MİLLÎ EĞİTİM BAKANLIĞI YAYINLARI ... DERS KİTAPLARI DİZİSİ` |
| OCR-tur (819 kar) | `MİLLİ EĞİTİM BAKANLIĞI YAYINLARI ... DERS KİTAPLARI ...` |

→ OCR düzgün **Türkçe** okuyor (İ/Ğ/Ş doğru; `eng` ise "MILLI EGITIM" — diyakritik kaybı → **tur şart**). Süsleme nokta-dizisi ("......") OCR'da gürültüye dönüşüyor (beklenen sınır).

**görsel-sanatlar OCR-adayı 6 sayfa:** 2'sinde gerçek metin (s.5 `MUSTAFA KEMAL ATATÜRK` portre altyazısı doğru okundu); kalanı gerçek **sanat/foto** → gömülü metin yok.

## 3. Bulgular (dürüst)
- **[DENEYSEL SONUÇ] OCR fallback çalışıyor + Türkçe yüksek-doğruluklu** — sessiz-delik (taranmış/text-in-image sayfa) kapandı. Zarif degradasyon: pytesseract/tesseract/tur yoksa çökmez (`ocr_available`=False, `ocr_page`=""); 10 birim testi + 375 suite yeşil.
- **[HATA→FIX] tessdata quoting:** `--tessdata-dir "yol"` config'inde pytesseract config'i boşlukla böldüğü için tırnaklar yola giriyordu (`Error opening data file "..."/tur.traineddata`) → OCR sessizce "" dönüyordu. **Fix:** `TESSDATA_PREFIX` env (boşluklu yola da dayanıklı). Teşhis: aynı sayfa tırnaklı=HATA, env=819 kar.
- **[SINIR — multimodal, Faz 5] OCR ≠ görsel anlama.** görsel-sanatlar içeriği metinde değil **görüntüde** (artwork); OCR yalnız gömülü METNİ kurtarır. Bu kitapların asıl açığı **multimodal** (Faz 5, ertelendi), OCR değil.
- **[VARSAYIM] Provenance:** OCR blokları `Block.ocr=True` taşıyor (parse düzeyi); `CanonicalUnit`'e taşınmadı (atıf OCR'dan mı geldi görünürlüğü) — opsiyonel iyileştirme.

## 4. Özet-PDF uçtan uca (özet çıkar butonu backing)
`build_canonical(pdf) → resolve_scope(pages) → Summarizer.summarize(units)` — retrieval KULLANMAYAN, kapsam-tabanlı ayrı mimari (soru-cevaptan bağımsız). Gerçek çalıştırma (bio, kapsam 6 sayfa):

| Ölçüt | Değer |
|---|---|
| n_units | 95 → **hiyerarşik (RAPTOR-benzeri)** |
| çıktı | detaylı, yapılandırılmış (başlık/alt-bölüm/kalın/liste) |
| atıf | her iddia `[N]`, gerçek span_id+sayfaya çözülüyor ([3]→s.2-4, [7]→s.12, [8]→s.12-13) |
| maliyet | $0.0147 |

**[DENEYSEL SONUÇ] Dürüst temellendirme:** kapsama bilerek konulan kapak/İstiklal Marşı/künye sayfalarını (1-4) özet **"biyoloji içeriği değil"** diye açıkça ayırdı, uydurmadı; asıl içeriği (laboratuvar güvenliği, s.12-13) detaylandırdı. Fail-closed + no-fake-filling korundu.

## 5. Aksiyon / backlog
- OCR: TAMAM (opsiyonel, test+demo kanıtlı). Toplu ingest'te `build_canonical(ocr=True)` ile açılır.
- Özet-PDF: TAMAM (mekanizma uçtan uca kanıtlı). Backlog: uzun kapsamda `max_tokens` artışı (demo 1500'de sonu kırpıldı); içerik-odaklı kapsamda atıf zenginliği (kapak sayfaları seyreltmişti).
- Multimodal (görsel anlama) — Faz 5, ertelendi (OCR kapsamı dışı).
- Durum: `İNSAN İNCELEMESİ BEKLİYOR` (nihai kabul Kadir).
