# 🪜 Hezarfen RAG — Adım Adım Plan (küçük adımlar)

> Mimari: [[mimari]] · Kapılar: [[benchmark]] · Kalite kaydı: [[deney-sonuclari]] · Maliyet: [[Maliyet]]
> Kural: her adım **küçük + kabul kriterli + test edilebilir**. Bitince ✅ + tarih.
> Kod: `hezarfen_rag/src/`, testler `hezarfen_rag/tests/{unit,integration,e2e}`.
> Model: **DeepSeek v4-flash** (zor soru-üretiminde v4-pro). Fine-tune YOK.
> **Veri:** gerçek `data/` kullanılır — **mock veri YOK** (düştü).
> **Git akışı:** TEK branch (`main`), **adım adım commit** (her küçük adım = 1 commit, geri dönülebilir). Feature-branch AÇILMAZ. Commit yazarı **Kadir**; commit'lerde AI/Claude adı/izi bulunmaz.
> Son güncelleme: 2026-08-29

## Durum özeti
- ✅ **Veri indirildi** (tüm ders/sınıf; lise 4-kaynak, ortaokul kitap). `hezarfen_rag/data/`.
- ✅ **Maliyet altyapısı** (`src/pricing`, `src/providers/deepseek`, `src/costlog`) + [[Maliyet]] otomatik.
- ✅ **Repo yapısı** `src/` + `tests/` (7 birim test geçiyor).
- ▶️ Sıradaki: **Faz 0** (12-bio corpus compiler + veri hijyeni).

---

## FAZ 0 — İskele & veri hijyeni  (vertical slice: 12-bio)  [her adım = 1 commit]
Amaç: temiz, atıflanabilir, sızıntısız kaynak; her şey buna dayanacak. Mock veri yok, gerçek `data/lise/12/biyoloji`.
- [x] **0.1** Repo `src/` + `tests/` iskele. → *kabul:* `python -m unittest` yeşil. **✅ 2026-08-29**
- [x] **0.2** Maliyet modülü + [[Maliyet]] otomatik. → *kabul:* örnek run tabloya düşer. **✅**
- [x] **0.3a** `src/ingest/pdf_parse.py` (PyMuPDF): sayfa → metin blokları + **koordinat (bbox)** + sayfa no. → *kabul:* 12-bio **187 sayfa** (186 metinli, 420K karakter), bbox tutarlı. **✅ 2026-08-29** (commit `0a32e96`)
- [x] **0.3b** Okuma sırası + blok tipi (başlık/paragraf/liste/caption/header/footer/label) + **2-sütun okuma sırası**. → *kabul:* sayfa 41'de header→başlık→sol sütun→sağ sütun doğru; 26 test yeşil (edge case + gerçek veri). **✅ 2026-08-29** (commit `8cdca2f`)
- [x] **0.3c** Tablo tespiti (pdfplumber) + **sıkı kalite filtresi** → yapısal JSON (satır/sütun + bbox). → *kabul:* sayfa 20 DNA/RNA tablosu (%100 dolu) yakalanır, sayfa 1/12 dekoratif kutu elenir; 38 test yeşil. Bulgu: kitap tablo-fakiri (270 ham → az gerçek). **✅ 2026-08-29** (commit `5e9fe36`)
- [x] **0.3d** **Görsel/şekil analizi** (`src/ingest/visuals.py`): union kaplama + sayfa sınıfı (figür-ağırlıklı/karma/salt-metin) + `render_region` (VLM için). → *kabul:* 12-bio %27 figür-ağırlıklı, cross-ders bulgular ([[bulgular]]); 51 test yeşil. **Bulgu:** görsel yoğunluk derse/sayfaya göre değişir → **sayfa-bazlı vision-router = maliyet tasarrufu**; diyagramlar vektör kompozit → bölge render. **✅ 2026-08-29**
- [x] **0.4a/b** **Sızıntı izolasyonu** (`src/ingest/isolate.py`): sayfa-düzeyi ön/arka-madde (içindekiler/kitap-tanıtımı/kaynakça/sözlük/dizin) + blok-düzeyi değerlendirme-soru & çoktan-seçmeli blokları → `Block.retrieval_disi`/`.retrievable`. → *kabul:* 12-bio 10 meta sayfa + 42 soru bloğu hariç, teaching korundu, **0 sızıntı** (hariç sayfada retrievable blok yok). **✅ 2026-08-31** (commit `d89cc73`). Bulgu: cevap anahtarı QR arkasında (metinde yok).
- [ ] **0.5** Kanonik doküman şeması + metadata (`sha256/sinif/ders/unite/kazanim/kaynak_turu/sayfa/bbox`) → normalize JSON. → *kabul:* her öğe eksiksiz metadata. *test:* unit.
- [x] **0.6** Türkçe normalize (`src/text/tr_normalize.py`): NFC, `I/ı İ/i`, `\xad`/BOM temizle, hece-bölünmesi birleştir, simge/alt-indis koru; `fold_for_match` (aksan korur). → *kabul:* 12 edge case + gerçek 12-bio quirk'leri (malzeme\xadler→malzemeler) doğrulandı. **✅ 2026-08-31** (commit `7470b00`)
- [x] **0.7** Curriculum graph omurgası (`src/curriculum/graph.py`): `kazanimlar.json` → `sinif→ders→unite→kazanim` (by_kod/by_id/units; JSON/bellek). → *kabul:* 12-bio 29 kazanım/4 ünite; vault 3505 kazanım/54 ders; 11 test. **✅ 2026-08-31** (commit `4924a2a`)
- [ ] **0.8** Konu özeti PDF parse (sütun sırası) + çalışma defteri JPG→OCR (Tesseract TR). → *kabul:* 3 örnekte okunur metin. *test:* integration.

## FAZ 1 — Text RAG baseline: **kaynakla konuşma**  (12-bio)
- [ ] **1.1** Chunking (çok-temsil): çocuk 150-300 tok + üst 700-1500 + atomik önerme. → *kabul:* chunk sayısı + metadata bütün; overlap ayarlı. *test:* unit.
- [ ] **1.2** Embedding: BGE-M3 (dense+sparse) yerel; her chunk vektörü. → *kabul:* 12-bio indekslenir; boyut/süre [[deney-sonuclari]] S3. *test:* integration.
- [ ] **1.3** İndeks: Qdrant yerel (dense) + rank_bm25 (lexical, TR normalize, 1 alan köksüz). → *kabul:* ANN recall ≥0.995 (exact'e karşı). *test:* integration.
- [ ] **1.4** Retrieval: BM25 top40 + dense top40 + sparse top30 → **RRF**. → *kabul:* Recall@20 ölç ([[benchmark]] hedef ≥0.98). *test:* integration.
- [ ] **1.5** Reranker: BGE-reranker-v2-m3 → ilk 8-12 + çeşitlilik + parent genişletme. → *kabul:* nDCG@10 ≥0.90; rerank kazancı %95 CI pozitif. *test:* integration.
- [ ] **1.6** Metadata filtresi + **kasa izolasyonu** (lise≠ortaokul, ders≠ders). → *kabul:* 0 yetkisiz sızıntı. *test:* integration (izolasyon).
- [ ] **1.7** Üretim: DeepSeek-flash, kaynak-sınırlı + **atıf (sayfa/bbox)** + çekimser. → *kabul:* faithfulness ≥0.99, desteksiz ≤%0.5, citation P/R ≥0.99/0.97. *test:* e2e.
- [ ] **1.8** **Golden set v1** (≥30, sonra büyüt): soru + zorunlu kanıt span + gold cevap; sızıntısız bölme. → *kabul:* [[benchmark]] §1 şemasına uygun. *test:* fixture.
- [ ] **1.9** Eval harness: DeepEval + RAGChecker → [[deney-sonuclari]] + [[Maliyet]] otomatik. → *kabul:* tek komut rapor üretir; her run maliyetiyle loglanır. *test:* e2e.

## FAZ 2 — Özet (RAPTOR)  (187 sayfa)
- [ ] **2.1** Extract-then-abstract: sayfa/bölüm atomik iddia → sayfa/görsele bağla. *kabul:* iddia-kaynak eşlemesi.
- [ ] **2.2** RAPTOR ağacı: alt-başlık → ünite → kitap (küme özetleri DeepSeek-flash). *kabul:* ağaç kurulur.
- [ ] **2.3** %5/%10/%20 özet + kazanım-kapsam matrisi. *kabul:* kapsam ≥0.95, kaynak-destekli ≥0.99, çelişki 0 ([[benchmark]]).
- [ ] **2.4** Özet eval: FActScore-tarzı + coverage + "özetten cevaplanan soru oranı". → [[deney-sonuclari]].

## FAZ 3 — Soru çözme  (veri boşluğu var — önce doldur)
- [ ] **3.1** **Veri:** eksik soru gövdeleri + görselleri topla; soru–kazanım eşle (sorular.json'daki `kazanimlar` boş). *kabul:* 12-bio için ≥X tam soru.
- [ ] **3.2** 5 koşul: closed-book / long-context / text-RAG / multimodal / **oracle**. *kabul:* 5 tablo ayrı.
- [ ] **3.3** Zengin çıktı: şık + kanıt zinciri + çeldirici-neden-yanlış + sayfa + kalibre güven. *kabul:* şema tam.
- [ ] **3.4** Sağlamlık: şık/etiket karıştır, kök yeniden yaz, görsel/metin ayır, nicelik/olumsuzluk. *kabul:* varyantlarda tutarlılık raporu.

## FAZ 4 — Soru üretme + benzer soru  ⏸️ ERTELENDİ (2026-08-31, sonra yapılacak)
> **ERTELENDİ** — Kadir kararı: önce diğer kısımlar (Faz 0-3, 5-6). Soru-üretme sonraya.
> **Tam tasarım hazır: [[soru-uretme]]** (kaynak: [[Literatür/Soru Üretme]]). Aşağısı özet adımlardır; detay/kapılar orada.
- [ ] **4.1** Kavram kartı derleyici (iddia/mekanizma/önkoşul/yanılgı/görsel/kazanım/kanıt). *kabul:* 1 kazanımda kart. → [[soru-uretme]] §1.2
- [ ] **4.2** Üretim hattı: blueprint → kanıt paketi → soru+cevap → **anahtarsız çözücü** → critic → kanıt denetleyici → dedup. *kabul:* yayın şeması ([[mimari]] §3) + kapılar ([[benchmark]] §3).
- [ ] **4.3** Benzer soru: gerçek EBA sorusu tohum → kNN → varyant; **ayrı kalibre**, aynı aile aynı forma girmez.
- [ ] **4.4** Öğretmen onay akışı + (sonra) psikometrik pilot.

## FAZ 5 — Multimodal (şekil/tablo)
- [ ] **5.1** Sayfa görüntüsü + region crop; şekil-caption bağla. *kabul:* şekil sorusu için crop retrieval.
- [ ] **5.2** DeepSeek-vision ile crop+caption+yakın paragraf → cevap (sayfa/bbox atıf). *kabul:* görsel-RAG > text-RAG mı? ([[benchmark]] ablation).

## FAZ 6 — 8. sınıf transfer
- [ ] **6.1** 8-fen + 8-mat aynı boru hattı; grade/domain drift analizi. *kabul:* release kapıları 8.'de de geçer.

## FAZ 7 — Graph / Agent (yalnız kanıtla)
- [ ] **7.1** Curriculum graph retrieval **sadece** multi-hop/önkoşul soruda; ablation kazancı varsa. 
- [ ] **7.2** Bounded agent (≤2-3 tur, iç kaynak, web yok) **sadece** kanıt yetersizliğinde; ablation kazancı varsa.

---
## Çalışma kuralları
- Her adım bitince: kabul kriterini ölç → [[deney-sonuclari]] (kalite) + [[Maliyet]] (maliyet) → ✅ işaretle.
- **Sızıntı ve atıf** her fazda kontrol edilir (en sık hata kaynağı).
- Bir bileşen ancak **ölçülen kazanç** verirse kalır ([[benchmark]] §5 ablation).
- Kod küçük PR'lar; testsiz adım "bitti" sayılmaz.
