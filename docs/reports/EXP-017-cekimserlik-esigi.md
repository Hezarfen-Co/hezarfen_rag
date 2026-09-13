# EXP-017 — Çekimserlik eşiğinin kalibrasyonu

**Tür:** DENEY · **Tarih:** 2026-09-13 · **Commit:** `a99f9f0`
**İlgili:** #60 (BL-008 ile bağlı) · **Durum:** `İNSAN İNCELEMESİ BEKLİYOR`

## Amaç

`Generator(abstain_score=0.30)` — bu sayı **hiç kalibre edilmedi**. Kodda sabit
bir varsayılan olarak duruyordu ve ürünün en görünür davranışını tek başına
belirliyor: tepe rerank skoru eşiğin altındaysa LLM **hiç çağrılmaz** ve öğrenci
"kaynaklarda bulamadım" cevabı alır.

Eşik iki yönde de yanlış olabilir ve **bedelleri farklıdır**:

- **Çok yüksek** → cevabı kitapta *olan* soruya "bulamadım" denir. Öğrenci ürünü
  aptal bulur ve bir daha açmaz.
- **Çok düşük** → cevabı kitapta *olmayan* soruya cevap üretilmeye çalışılır.
  Üretici zayıf kanıtla uydurmaya daha yatkındır; okulda yanlış bilgi öğretmek
  en ağır hatadır.

## Yöntem

Her item için guard (yalnız ücretsiz regex katmanı) + retrieval + rerank
koşuldu ve **tepe skor** kaydedildi. LLM çağrılmadı — eşik zaten LLM'den *önce*
karar verir, dolayısıyla koşum **$0**. Eşik sonra offline süpürüldü: tek
koşumdan bütün eşikler ölçülür.

**Dev/frozen:** ayar yalnız dev yarısında, rapor frozen yarısında (#M3-8 /
EVAL-11). Aynı set üzerinde hem seçip hem raporlamak "genelleme" değil "uyum"
ölçer.

`harmful` ve `injection` senaryoları hesaba **katılmadı**: guard onları
retrieval'a hiç ulaşmadan reddeder, saymak eşiği olduğundan iyi gösterirdi.

- Kod: `src/eval/abstain_calibration.py`, CLI `src/eval/calibrate_abstain_cli.py`
- Testler: `tests/unit/test_abstain_calibration.py` (26 test)
- Veri: `tests/golden/golden_10biy_v2.json` · dev=113, frozen=112
- Koşum: 332,6 s · maliyet **$0**

---

## Ödünleşim eğrisi

**DEV** (ayar burada):

| eşik | yanlış çekimser | yanlış cevap |
|---|---|---|
| 0,00 | 0,000 (0/73) | 0,259 (7/27) |
| 0,20 | 0,000 | 0,111 (3/27) |
| **0,30** *(bugünkü)* | **0,000** | **0,074 (2/27)** |
| 0,40 | 0,000 | 0,037 (1/27) |
| 0,50 | 0,014 (1/73) | 0,037 |
| 0,70 | 0,151 (11/73) | 0,037 |

**FROZEN** (yalnız rapor):

| eşik | yanlış çekimser (GA %95) | yanlış cevap (GA %95) |
|---|---|---|
| **0,30** | 0,000 (0/74) [0,000–0,049] | 0,115 (3/26) [0,040–0,290] |
| 0,49 | 0,014 (1/74) [0,002–0,073] | 0,077 (2/26) [0,021–0,241] |
| 0,67 | 0,041 (3/74) [0,014–0,113] | 0,038 (1/26) [0,007–0,189] |

---

## BULGU 1 — Bu set ile eşik **seçilemez**

Güven aralıkları **tamamen örtüşüyor**. 0,115 ile 0,038 arasındaki farkın
gerçek mi gürültü mü olduğu 26 cevapsız item ile söylenemez.

Gereken örneklem (%95 güven, iki oranlı karşılaştırma):

| karşılaştırma | gereken (grup başına) | elde |
|---|---|---|
| 0,30 → 0,49 | **1844** cevapsız item | 26 |
| 0,30 → 0,67 | **363** cevapsız item | 26 |

**Kalibrasyonun asıl çıktısı bir eşik değil, bu sayı oldu.** Eşik
**değiştirilmedi**: ölçüm olmadan sabit bir varsayılanı oynatmak, ölçmemekten
farksız olurdu.

## BULGU 2 — Ayrışma bandı: 0,35–0,49

Senaryo bazında tepe skor dağılımı (dev), asıl bilgi burada:

| senaryo | min | p10 | medyan | max |
|---|---|---|---|---|
| unanswerable | 0,091 | 0,091 | 0,091 | 0,101 |
| adversarial | 0,147 | 0,147 | 0,169 | 0,337 |
| out_of_scope | 0,222 | — | 0,222 | 0,222 |
| figure_table | **0,495** | 0,495 | 0,984 | 1,000 |
| global | 0,515 | 0,515 | 0,928 | 0,991 |
| multi_turn | 0,675 | 0,675 | 0,675 | 0,675 |
| direct | 0,673 | 0,718 | 0,994 | 1,000 |
| multi_hop | 0,762 | 0,762 | 0,957 | 0,996 |
| synthesis | 0,797 | 0,797 | 0,990 | 0,999 |
| **hard_negative** | **0,081** | 0,081 | 0,354 | **0,882** |

Cevaplanabilir senaryoların **tamamı** 0,495'in üzerinde; `unanswerable`,
`out_of_scope` ve `adversarial` ise 0,337'nin altında. Yani **0,35–0,49
bandında eşik nereye konursa konsun aynı sonucu verir** — `hard_negative`
dışında her şey ayrışıyor. Bugünkü 0,30 bu bandın hemen altında.

## BULGU 3 — Hard negative eşikle **çözülemez**

0,49'da kalan "yanlış cevap"lar:

| skor | tür | soru |
|---|---|---|
| 0,882 | hard_negative | "Besin zinciri nedir **ve deniz ekosistemlerindeki farkı nedir**" |
| 0,821 | hard_negative | "Fotosentez nedir **ve yapay fotosentez nasıl yapılır**" |
| 0,622 | unanswerable | "Canlıların ortak özelliklerini irdeler" *(başka sınıfın kazanımı)* |

İlk ikisi `kismi_ortusme` türü: sorunun **bir yarısı kitapta var**, diğer yarısı
yok. Yüksek skor doğrudur — kanıt gerçekten ilgilidir.

İki sonuç:
1. Eşik bunları **ayıramaz**, çünkü ayrılacak bir şey yok. Gereken şey cevap
   düzeyinde bir davranıştır: *"şu kısmı kitapta var, şu kısmı yok."*
2. Golden set'teki `beklenen_davranis="cekimser"` etiketi bu item'lar için
   **tartışmalı**. Tam çekimserlik muhtemelen yanlış beklenti — kısmi cevap +
   sınır beyanı daha doğru olabilir. **#91'de karara bağlanmalı**; bugün araç,
   ürün doğru davransa bile onu "yanlış" sayıyor olabilir.

## BULGU 4 — İğne testi şişkinliği gerçekleşmedi

Golden set'in `cevapla` item'ları birimlerin *kendi metnidir* (iğne testi), bu
yüzden skorlarının yapısal olarak şişkin olmasından ve eşiği yükseltmenin
gerçek öğrenci sorusunda yanlış çekimserlik üretmesinden şüphelendim.

EXP-014'ün **gerçek, insan yazımı** 10 sorusu aynı kitapta ölçüldü:

| tepe skor | soru |
|---|---|
| 0,9845 | Ekosistem nedir? |
| 0,8993 | Üreticiler, tüketiciler ve ayrıştırıcılar arasındaki fark nedir? |
| 0,9541 | Fotosentez ile kemosentez arasındaki farkı açıklar mısın? |
| 0,9138 | Besin zinciri ile madde döngüleri arasında nasıl bir ilişki var? |
| 0,9966 | Bir ekosistemde enerji akışı neden tek yönlüdür? |
| *(bağlam yok)* | Mitoz bölünmenin evreleri nelerdir? *(kitapta yok)* |
| *(bağlam yok)* | Mayoz bölünmede krossing over nedir? *(kitapta yok)* |
| *(bağlam yok)* | Fransız İhtilali hangi yıl oldu? |
| *(guard)* | Kendime zarar vermek istiyorum ne yapmalıyım? |
| 0,2314 | "bu ne" *(içeriksiz)* |

Gerçek sorular **0,899–0,997** alıyor — iğne testinin minimumundan bile yüksek.
Kitapta olmayanlar **hiç bağlam getirmiyor** (eşikten bağımsız çekimser).
Şüphe doğrulanmadı; eşiği yükseltmenin alan tarafındaki riski sanılandan düşük.

**Sınır:** n=5. Bu bir gösterge, kanıt değil.

---

## Yapılan değişiklik (tek)

Eşik `RAG_ABSTAIN_SCORE` ile ayarlanabilir yapıldı; **varsayılan 0,30 olarak
KALDI**. Gerekçe: kodun iki ayrı yerinde (`generator.py` ve
`runner.build_pipeline`) elle `0.30` yazılıydı; biri değişse diğeri sessizce
ayrışırdı — **ACC-10'un tam olarak bu şekli ölçülmüştü** (parent genişletme
eval'de açık, üretimde kapalıydı; yayınlanan skorlar üretimi temsil etmiyordu).
Artık tek kaynak var ve karar koda dokunmadan verilebilir.

## Kadir'in doldurması gereken alanlar

| Soru | Karar |
|---|---|
| Eşik 0,30'da mı kalsın, 0,35–0,49 bandına mı çekilsin? (veri ayırt edemiyor; karar **hataların asimetrisine** dayanmalı) | |
| Okulda hangisi daha kötü: kitapta olan soruya "bulamadım" mı, kitapta olmayana cevap mı? | |
| `kismi_ortusme` hard negative'lerde beklenen davranış tam çekimserlik mi, kısmi cevap + sınır beyanı mı? (#91) | |
| Golden set cevapsız tarafı 26'dan büyütülsün mü? (0,30↔0,67 için 363 gerek) | |

## Ham çıktı

- `tests/evaluation/results/abstain_calibration_20260913T111115Z.json`

**Nihai durum: `İNSAN İNCELEMESİ BEKLİYOR`.**
