# EXP-006 — Çok-ders özet + özette kaynak görselleri (multimodal özet)

- **Tarih:** 2026-09-06
- **Ham çıktı:** `scratchpad/exp006_ozet_mm.py`, `exp006c.py`, `exp006d.py` + ham teşhis.
- **Amaç (Kadir):** özet çok-derse genelleşiyor mu + "özette kaynaktan görseller de kullanılabilir" mi.

## 1. Çok-ders özet ✅
- **kimya** (kapsam s.112-117, 105 birim → hiyerarşik): detaylı, yapılandırılmış özet — başlık/alt-başlık + **ayrımsal damıtma TABLOSU** + izomerlik; her iddia `[N]` atıflı, 7 atıf, $0.0231. Konu: Alkanlar/Alkenler/İzomerlik.
- **fizik** (kapsam s.13-18, 206 birim → hiyerarşik): "Çembersel Hareket" ünitesi yapılandırılmış özeti, 8 atıf, $0.0328.
- → **Özet dersler arası genelleşiyor** (retrieval'dan ayrı, kapsam-tabanlı mimari; fail-closed korunuyor).

## 2. Multimodal özet — mimari ✅, exp-model kararsız ⚠️
- **Mimari çalışıyor:** `build_canonical(vlm=True)` → `gorsel_aciklama` birim → `resolve_scope` kapsama alıyor → Summarizer özetliyor + **görsele atıf** (span_id=sayfa+bbox) verebiliyor. EXP-006'da görsel-birim kapsama girdi ve boru hattından geçti.
- **VLM captioning içerik döndürdüğünde doğru:** görsel-sanatlar portre/etkinlik (EXP-004) + kimya s.37 elektrokimya diyagramı ("elektrokimyasal hücreler + iki tablo") ham çağrıda doğru betimlendi.
- **⚠️ BULGU — `deepseek-v4-flash-vision-exp` kararsız:** yoğun diyagram/tablo sayfalarında model **tüm completion bütçesini reasoning'e harcayıp BOŞ içerik** döndürüyor (doğrulandı: `reasoning_tokens=512`@max512 / `=1024`@max1024, `content_len=0`). Rate-limit/hata değil; deneysel modelin instabilitesi. Basit görsellerde (portre, başlık sayfası) çalışıyor. VLMCaptioner bunu zarifçe yutuyor (boş → görsel-birim eklenmez) → pipeline çökmez ama o görsel kaçar.
- **Sonuç:** görselin ÖZETTE görünür şekilde kullanıldığı temiz demo, exp-modelin karmaşık-görsel boş-dönüşü yüzünden aralıklı. Mimari hazır; darboğaz model.

## 3. Bulgular / öneri (dürüst)
- **[DENEYSEL SONUÇ] Çok-ders özet TAMAM** — kimya/fizik detaylı+atıflı özet üretiyor.
- **[DENEYSEL SONUÇ] Multimodal-özet mimarisi TAMAM** — görsel captionları özet kapsamına girip atıflanabiliyor (kod+plumbing kanıtlı).
- **[ZAAF — model] exp DeepSeek-VL karmaşık görselde boş içerik** (all-reasoning). "Bedava + mevcut key" avantajı var ama ÜRETİM için güvenilmez.
- **[ÖNERİ] Güvenilir multimodal için sağlayıcıyı değiştir:** `VLM_BASE_URL/VLM_MODEL/VLM_API_KEY` ile **stabil bir vision API'ye** (Gemini 2.0 Flash / GPT-4o-mini) geç — sağlayıcı-bağımsız tasarım (providers/vlm.py) tam da bunun için. Kod değişmez, yalnız env.
- **[BACKLOG]** stabil VLM ile tam-korpus caption batch (rate-limit backoff); captioning'i altyazılı/diyagram (mixed) sayfalara hedefle (figure_heavy-düşük-metin = çoğu dekoratif ayraç); özet-görsel demo stabil modelde tekrarla.

## 4. ÇÖZÜM — exp-VL boş-içerik giderildi ✅ (2026-09-06)
Kadir "exp-model yeter" dedi → sorunu exp-model içinde çözdük. Ampirik prob (`scratchpad/vl_fix_probe.py`, s.37):

| Yöntem | İçerik | Not |
|---|---|---|
| baseline mt512 | **len=0** | reasoning=512, bug |
| **`reasoning_effort:"none"`** | **len=2362** ✅ | reasoning kapalı, boşa token yok — SEÇİLEN |
| `thinking:{type:disabled}` | len=2469 ✅ | alternatif |
| max_tokens=4096 | len=3654 ✅ | çalışır ama 2038 reasoning token israf |
| düşük dpi (110) | len=0 | işe yaramadı |

**Fix (commit sonrası):** `default_captioner()` DeepSeek yolunda `extra_params={"reasoning_effort":"none"}` enjekte edilir (sağlayıcı-bağımsız kalır — VLM_* ile başka sağlayıcıda enjekte edilmez). Doğrulama: s.37 (önceden boş) artık zengin içerik + özet **diyagramı içeriyor** ("A/B pilleri şeması, Cu/Ag elektrot, tuz köprüsü, voltmetre, elektron akışı"). VLM captioning artık karmaşık diyagramda da güvenilir.

## 5. Aksiyon
- Özet çok-ders ✅ · Multimodal-özet mimari ✅ · **exp-VL boş-içerik ✅ giderildi (reasoning_effort=none).**
- **Kalan (backlog):** tam-korpus caption batch; görsel-span atıf tam-eşleşmesi (şu an içerik var ama atıf paylaşılan sayfaya düşebiliyor — citation-granülerlik); captioning'i diyagram sayfalarına hedefleme.
- Durum: `İNSAN İNCELEMESİ BEKLİYOR`.
