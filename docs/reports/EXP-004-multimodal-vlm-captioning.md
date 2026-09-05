# EXP-004 — Multimodal: VLM ile görsel içerik captioning (Faz 5, #23)

- **Tarih:** 2026-09-06
- **Commit (kod):** `d6fb062` (iskelet) + `a4ea060` (DeepSeek-VL varsayılan)
- **Ortam:** DeepSeek API `deepseek-v4-flash-vision-exp` (canlı `/models` ile doğrulandı — **mevcut `DEEPSEEK_API_KEY` yeter, yeni key YOK**), PyMuPDF render 200 dpi.
- **Ham çıktı:** `scratchpad/vlm_demo.py`.
- **Motivasyon (EXP-003):** OCR yalnız gömülü metni verir; görsel-sanatlar/şekil/diyagram içeriği görüntüde → indekse/özete girmiyordu.
- **Karar (Kadir 2026-09-06):** yerel VLM DEĞİL, API. → Araştırma sonucu DeepSeek API'nin vision modeli çıktı; mevcut key ile kullanıldı.

## 1. Mimari (sağlayıcı-bağımsız)
- `src/providers/vlm.py` — `VLMCaptioner`: OpenAI-uyumlu `/chat/completions` (mesajda `image_url` data-URI). base_url/model/key **env'den** (`VLM_BASE_URL/VLM_MODEL/VLM_API_KEY`) → herhangi VLM (OpenRouter/Gemini-compat/GPT-4o-mini/Qwen). `default_captioner()`: env yoksa DeepSeek-VL'e düşer.
- `src/ingest/visual_caption.py` — `caption_visual_units`: **figure_heavy** sayfaları (visuals.py sınıfı) captionlar → `kind="gorsel_aciklama"` `CanonicalUnit` (gerçek span_id: sayfa+bbox). `merge_visual_units`: okuma-sırasına yerleştirir.
- `build_canonical(vlm=True)` hook (default KAPALI). Zarif degradasyon: captioner yoksa boş.
- **9 birim testi** (hermetik) + 384 toplam yeşil.

## 2. Canlı kanıt (görsel-sanatlar, gerçek API)
| Sayfa | Çıktı | Süre | Token in/out |
|---|---|---|---|
| 5 | **portre** doğru betimlendi ("belden yukarısı, hafif sağa dönük erkek, saçları kırlaşmış" = Atatürk portresi) | 5.8s | 619/400 |
| 40 | "BOYAMA" etkinlik sayfası + dekoratif şerit (yıldız/gezegen/hilal) | 4.6s | 619/400 |
| 80 | "KESME" sayfası + motifler (halka/yıldız/balık), filigran metin | 4.6s | 619/393 |

→ Türkçe, nesnel, **uydurma yok**. OCR'ın göremediği görsel içerik (portre resmi) metinleştirildi.

**Maliyet:** ~619 in + ~400 out token/sayfa → vision fiyatıyla (~in 0.44 / out 1.32 per 1M) **≈ $0.0008/sayfa**. görsel-sanatlar'ın ~50 figure_heavy sayfası ≈ $0.04. Ucuz; ingest'te bir kez.

## 3. Bulgular (dürüst)
- **[DENEYSEL SONUÇ] Multimodal captioning çalışıyor + mevcut key ile** — görsel içerik artık mevcut boru hattında (embed→retrieve→rerank→generate→özet) metin gibi aranır/özetlenir, atıf gerçek görsele (sayfa+bbox) çözülür. "Her kaynaktan her bilgi" hedefinin görsel ayağı açıldı.
- **[VARSAYIM] Kapsam:** captioning **sayfa** düzeyinde (figure_heavy sayfa = 1 çağrı) — figür-başı bölge değil. Provenance sayfa+tam-bbox. Figür-başı (daha ince atıf) ileride.
- **[SINIR] Model "exp":** `deepseek-v4-flash-vision-exp` deneysel — kalite/kararlılık izlenmeli; kod sağlayıcı-bağımsız (Gemini/GPT-4o-mini'ye env ile geçilebilir).
- **[BACKLOG] Tam-korpus captioning batch'i KOŞULMADI** (maliyet-bilinçli); toplu ingest'te `build_canonical(vlm=True)` ile açılır. `gorsel_aciklama` provenance'ı üretimde flag'lenebilir (görsel-türevli metin, düşük-kesinlik farkındalığı).

## 4. Aksiyon
- #23 multimodal: **çekirdek TAMAM** (kod+canlı kanıt); tam-korpus captioning + figür-başı granülerlik backlog.
- Sıradaki (Kadir yönü): #24 ayırt edici metrik + non-bio gold.
- Durum: `İNSAN İNCELEMESİ BEKLİYOR` (nihai kabul Kadir).
