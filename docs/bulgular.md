# 🔬 Korpus Bulguları — Görsel / Tablo / Diyagram

> Amaç: **kanıta dayalı bulgular** çıkarıp dil modelini **verimli** kullanmak ve
> RAG'i **doğru beslemek** (hangi sayfa pahalı vision'a, hangisi ucuz metne).
> Kod: `src/ingest/visuals.py` + `tables.py` · Yöntem: union (grid) kaplama + PyMuPDF.
> İlgili: [[mimari]] · [[plan]] · [[benchmark]] · [[Maliyet]] · kaynak [[Literatür/Hezarfen]]
> Ölçüm tarihi: 2026-08-29 (gerçek `data/` üzerinde bizzat çalıştırıldı)

## Bulgu 1 — Görsel yoğunluk **derse ve sayfaya göre çok değişir** (per-page routing şart)
Union görsel-kaplama ölçümü (üst üste binmeyi saymaz):

| Ders (kitap) | Sayfa | Figür-ağırlıklı (görsel≥%40) | Ort. görsel kaplama | Medyan parça/sayfa |
|---|---|---|---|---|
| lise/12 biyoloji | 187 | **%27** | %30 | 14 |
| lise/12 fizik | 282 | %15 | %19 | 5 |
| lise/12 kimya | 184 | **%5** | %16 | 4 |
| lise/12 matematik | 179 | **%42** | %34 | 2 |
| ortaokul/8 fen bilimleri | 292 | **%41** | %35 | 13 |
| ortaokul/8 matematik | 109 | %35 | %32 | 4 |

→ **Ders bazlı varsayım yapılamaz** (kimya %5 ↔ matematik %42). Yönlendirme **sayfa görsel-kaplamasına** göre yapılmalı.

12-bio sayfa sınıf dağılımı: **figür-ağırlıklı 50 (%27) · karma 94 (%50) · salt-metin 43 (%23)**.

## Bulgu 2 — Diyagramlar **vektör kompozit** (embedded çekme → bölge RENDER et)
Sayfa başına görsel-parça: medyan 14, **max 3251** (12-bio). Yani şekiller tek raster foto değil, yüzlerce vektör parçasından oluşuyor. Sonuç: `page.get_images()` ile embedded raster çekmek şekli KAYBEDER. Doğru yol → **şekil bölgesini render et** (`visuals.render_region` PNG) + caption + yakın paragraf ile VLM'e ver ([[Literatür/Hezarfen]] §görseller).
- Not: matematikte parça az (medyan 2) ama figür-ağırlıklı %42 → büyük tek grafik/geometri şekilleri; biyoloji/fen'de çok parça → yoğun kompozit diyagram. İkisi de render-region ile çözülür.

## Bulgu 3 — Tablolar az + dekoratif-kutu gürültüsü yüksek (sıkı filtre şart)
12-bio: ham `find_tables` **270** → kalite filtresi (dolu≥%60, ≥2×2) sonrası **~az gerçek tablo**. Örnek: sayfa 12 güvenlik-ikon kutusu (%50) elenir, sayfa 20 DNA/RNA karşılaştırma tablosu (%100) tutulur. Kitap tablo-fakiri (proz + diyagram ağırlıklı). → filtresiz tablo çıkarımı LLM'i çöp bağlamla besler.

## İmâ — verimli LLM + doğru RAG besleme
1. **Görsel-kaplama router (maliyet):**
   - `<%10` (salt-metin, 12-bio'da %23) → **DeepSeek-flash metin** (ucuz), VLM YOK.
   - `%10–40` (karma, %50) → flash + gerekirse şekil crop.
   - `≥%40` (figür-ağırlıklı, %27) → **DeepSeek-vision** (render-region crop + caption).
   → Sayfaların ~1/4'ü pahalı vision'a; ~1/4'ü tamamen ucuz metne. Sayfa-bazlı yönlendirme = ciddi maliyet tasarrufu. Ölçülen tasarruf her deneyde [[Maliyet]]'e düşecek.
2. **Şekil temsili:** render-region PNG + caption + metindeki atıf birlikte (OCR-only kullanma).
3. **Tablo:** yalnız filtre-geçen tabloları yapısal (satır/sütun+bbox) besle; dekoratif kutuyu ASLA.
4. **Chunk/besleme:** salt-metin sayfalarda düz metin chunk; figür sayfalarında metin + şekil-crop birlikte "kanıt paketi".
5. **Sonraki (0.4):** soru/cevap-anahtarı sayfaları retrieval'dan izole (sızıntı yasağı) — ayrı bulgu adımı.

## Doğrulama
- Kod: `src/ingest/visuals.py` (`_grid_coverage` union, `analyze_document`, `render_region`), `tables.py` (`is_real_table`).
- Testler: `tests/unit/test_visuals.py` (union/eşik/PNG), `tests/unit/test_tables.py`, `tests/integration/test_visuals.py` + `test_tables.py` (gerçek 12-bio). Tümü yeşil.
- Bu tablo gerçek `data/` üzerinde `analyze_document` ile üretildi (uydurma değil).
