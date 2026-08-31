# ✍️ Hezarfen — Soru Üretme Mimarisi

> **Kaynak literatür:** [[Literatür/Soru Üretme]] (bu doküman onun uygulanabilir özetidir; bölüm no'ları oraya atıf).
> Genel RAG: [[mimari]] · Adımlar: [[plan]] Faz 4 · Kalite kapıları: [[benchmark]] · Kalite kaydı: [[deney-sonuclari]] · Maliyet: [[Maliyet]] · Buglar: [[buglar]]
> Kısıt: **DeepSeek v4-flash** (zor üretimde v4-pro); **fine-tune YOK**. Son güncelleme: 2026-08-29

## 0. Temel ilke (§ literatür 1-2)
Güçlü ürün "PDF → 100 soru" DEĞİL; **kanıta bağlı + kapsam planlı + otomatik ret kapılı + uzman incelemeli + psikometrik öğrenen** bir madde geliştirme hattıdır. Akıcılık ve "uzman beğenisi" kanıt değildir — **öğrenci pilotu zorunlu**. Bloom etiketi tek başına kanıt modeli değildir; gözlenebilir işlem ver ("iki seriyi karşılaştır", "kuralı yeni örneğe uygula").

## 1. Hat (uçtan uca) — §12-14
```
Önem/blueprint (§12)  →  Kavram kartı (§12)  →  Üretici (§13)
   →  Bağımsız çözücü (anahtarsız, §13)  →  Eleştirici (§13)
   →  Kanıt denetleyici (atıf sayfa/bbox)  →  Klon & sızıntı kontrolü (§14)
   →  Öğretmen onayı  →  (düşük-riskli pilot)  →  Psikometri (§ CTT/IRT)
```

### 1.1 Önem analizi + blueprint (§12)
Tek modele "önemli yerler nere?" SORULMAZ. Her bilgi birimine öncelik puanı: müfredat ağırlığı + kazanım eşleşmesi + önkoşul merkeziliği + pedagojik rol (tanım/ilke/prosedür/örnek/neden-sonuç/karşılaştırma/istisna/sık-hata/tablo-şekil/özet) + öğretmen-sınav kanıtı + değerlendirilebilirlik − tekrar. **Blueprint optimizasyonu** (sadece en yüksek puanı alma): tüm zorunlu kazanımlar kapsansın, Bloom dağılımı hedefe uysun, aynı kazanım fazla tekrar etmesin, tablo/şekil/uygulama kotası, istisna & yanılgılar kaybolmasın, her seçime "neden önemli + kaynak" gösterilsin.

### 1.2 Kavram kartı (§12-13) — üretimden ÖNCE derlenir
Doğrulanmış temel iddialar · mekanizma/süreç zinciri · gerekli-yeterli koşullar · örnek + karşı-örnek · önkoşul kavramlar · **yaygın öğrenci yanılgıları** · görsel/tablo temsilleri · kazanım · kaynak kanıtları (sayfa/bbox).

### 1.3 Üretici / Bağımsız çözücü / Eleştirici (§13) — GİRDİLERİ FARKLI
- **Üretici** görür: kazanım, Bloom, soru tipi, zorluk hedefi, kanıt paketi, benzer uzman maddeleri, gerçek hata örnekleri. Üretir: kök, doğru cevap, çeldiriciler, çözüm, **her iddia için kaynak id**, **her çeldirici için yanlış-çözüm izi**, riskler.
- **Bağımsız çözücü**: doğru-cevap etiketini ve üreticinin açıklamasını GÖRMEZ; soruyu kanıttan yeniden çözer, kaynak göstererek cevaplar. Kontrol: aynı cevaba ulaştı mı? kanıt yetiyor mu? birden çok seçenek savunulabiliyor mu? dış bilgi gerekiyor mu?
- **Eleştirici**: kaynak-dışı iddia · belirsiz/eksik soru · çoklu-doğru · hiç-doğru-yok · dil/okuma düzeyi · yanlılık · seçenek-uzunluğu ipucu · dilbilgisi uyumu ipucu · kök↔doğru-seçenek aşırı örtüşme · "her zaman/asla" · kazanım tekrarı.
> ⚠️ **Kısıt notu:** aynı model ailesini (DeepSeek) 3 kez çağırmak TAM bağımsızlık vermez (hatalar korelasyonlu). Telafi: **deterministik kurallar** + farklı prompt/temperature + v4-pro'yu eleştirici rolünde + **uzman örneklemi**. Zayıf self-verification güvenilmez (§13).

### 1.4 Çeldirici — iki mod (§ literatür 5, "Türk öğrenci hata bankası")
- **Katı kaynak modu:** çeldiriciler yalnız PDF'den doğrulanır; kontrollü dönüşümler (nitelik değiştir, neden-sonuç ters, komşu kategori, tablo satır/sütun karıştır, yanlış birim/işaret, adım sırası bozma).
- **Kaynak + yanılgı bankası modu:** anonim gerçek öğrenci yanlışları + öğretmen etiketleri; her çeldiricide `misconception_id` + veri kaynağı. Anahtar yine PDF'den cevaplanabilir olmalı.
- Her çeldirici 3 şart: kaynağa göre yanlış · aynı semantik/dilbilgisi türü · gerçek/makul yanlış muhakeme. (LLM makul-yanlış üretir ama gerçek öğrenci yanılgısını bilmez → **hata bankası rekabet avantajı**.)

### 1.5 Klon & sızıntı & güvenlik (§14)
- **İç klon:** MinHash/n-gram + BM25 + embedding + sayı/değişken normalize + çözüm-ağacı benzerliği; aynı aileden 2 madde aynı forma girmez.
- **Cevap ipucu sızıntısı:** doğru seçenek hep uzun · kök örtüşmesi · tek seçeneğin gramer uyumu · "hepsi/hiçbiri" · görsel etiketi cevabı veriyor · dosya adı/açıklama cevap içeriyor.
- **Dışarı sızmış madde:** parmak izi + anlamsal indeks + anomali (ani tam başarı, süre) + parametre drift.

## 2. Yayınlanabilir madde şeması
```json
{ "soru_id","sinif","ders","mufredat_surumu","kazanimlar":["12.x.x.x"],
  "bilissel_duzey","soru_metni","secenekler":[],"dogru_cevap","cozum",
  "celdirici_gerekceleri":{"A":{"misconception_id","why":"..."}},
  "kanitlar":[{"source_id","page":36,"bbox":[]}],
  "gorsel_bagimliligi":true,"zorluk_hedefi":0.55,"uzman_onayi":false }
```

## 3. Model rolleri (DeepSeek kısıtı)
| Rol | Model | Not |
|---|---|---|
| Üretici | v4-flash (zor: v4-pro) | kanıt paketi + few-shot (kazanım/tip'e göre retrieval ile seçili) |
| Bağımsız çözücü | v4-flash (farklı prompt/temp) | anahtarı görmez |
| Eleştirici | v4-pro + **deterministik kurallar** | aynı-aile bağımsızlığı zayıf → kural + uzman telafi |
| Kanıt denetleyici | kurallar + flash | her iddia sayfa/bbox'a bağlı mı |
> Her üretim maliyeti [[Maliyet]]'e `module="soru-uret"` / `"benzer-soru"` olarak düşer (birim = 1 onaya hazır soru, ret'ler amortize).

## 4. Değerlendirme (§15) — kapılar [[benchmark]]'ta
- **Pilot öncesi:** kaynak doğruluğu/kapsamı · kaynak-iddia entailment · cevaplanabilirlik · tek-doğru oranı · belirsiz oranı · kazanım/Bloom uzman uyumu · blueprint sapması · yinelenen oranı · **ilk öğretmen kabulü ≥%85** · düzenleme süresi · kaynak-dışı bilgi oranı. **Yayın kapısı: doğru anahtar + kaynak desteği %100; belirsiz/çoklu-doğru ≤%1.**
- **Pilot sonrası (psikometri):** madde güçlüğü p · point-biserial ≥0.25 (tercih 0.30+) · çeldirici seçim oranı · işlevsiz çeldirici · IRT 2PL/3PL · **DIF** (sınıf/cinsiyet/okul). Klasik ~200 yanıt, kararlı IRT/DIF 500+.
- **Benzer soru:** varyant ≠ eşit güçlük (§ Westacott) → ayrı kalibre; gerçek EBA sorusu = gold.

## 5. Geliştirme sırası (§16 → bizim Faz 4 alt-adımları)
1. Kanıt grafiği + provenance (Faz 0'dan gelir) → 2. blueprint editörü + kavram kartı → 3. kaynağa-bağlı MCQ üretimi → 4. üretici–bağımsız-çözücü–eleştirici → 5. öğretmen onayı + denetim izi → 6. uzman kabul/düzenleme ölçümü. **Sonra:** Türk hata bankası → çözüm-adımı/hata-kodu retrieval → düşük-riskli pilot → CTT + çeldirici analizi → madde ailesi/klon yönetimi. **Daha sonra (bu RAG projesinin ÖTESİ, literatürde var):** anchor'lı IRT/CAT/shadow-test, DIF/drift/exposure, BKT/G-DINA öğrenci modeli, önkoşul grafiği, unutma modeli, haftalık planlayıcı, açık-uçlu OCR+rubric puanlama.

## 6. Kırmızı çizgiler (§ literatür sonuç)
- Kaynak bölgesi olmayan anahtar üretime giremez.
- "Model zor dedi" psikometrik güçlük sayılmaz.
- Aynı şablon varyantları eşdeğer kabul edilmez.
- Uzman + öğrenci pilotundan geçmeyen madde yüksek-riskli sınavda kullanılmaz.
- Başarı metriği üretilen soru SAYISI değil; **değişikliksiz uzman kabulü + doğrulanmış kaynak kapsamı + ayırt edicilik + işleyen çeldirici + DIF güvenliği.**
