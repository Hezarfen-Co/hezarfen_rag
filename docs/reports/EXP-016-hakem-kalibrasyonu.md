# EXP-016 — LLM hakeminin kalibrasyonu (negatif + pozitif kontrol)

**Tür:** DENEY (ölçüm aracının kendisi) · **Tarih:** 2026-09-13 · **Commit:** `dcef83d`
**İlgili:** #72 (EXP-010 #M3-9, bulgu EVAL-06) · **Durum:** `İNSAN İNCELEMESİ BEKLİYOR`

## Amaç

LLM hakemi **hiç kalibre edilmemişti**. Skorları rapora giriyordu ama hakemin kötü
bir cevabı kötü bulup bulmadığı hiç sınanmamıştı.

Kalibre edilmemiş hakem **ölçümün tamamını geçersiz kılar**. Her şeye 0,9 veren bir
hakem "ürün mükemmel" der; her şeye 0,3 veren bir hakem gerçek iyileşmeyi gizler.
İkisi de aynı ölçüde yanlıştır ve ikisi de **tek yönlü bakışta görünmez**.

## Yöntem

EXP-013'te öğrenilen ders gereği **iki yön birden** ölçüldü:

- **Negatif kontrol** (10 vaka): kasten bozulmuş cevap → hakem DÜŞÜK vermeli.
  Beş bozma türü, her birinden 2 vaka:
  `fabricated_fact` (gold cevabın içine bağlamda geçmeyen somut bir cümle eklenir) ·
  `negation` (bir iddianın yönü tersine çevrilir) · `off_topic` · `empty` · `evasive`.
- **Pozitif kontrol** (10 vaka): gold cevabın **kendisi** → hakem YÜKSEK vermeli.

Pozitif kontrol olmadan "her şeye 0,1 veren" bozuk bir hakem **tam puan alırdı**.

Ölçü: `discrimination = ort(pozitif) − ort(negatif)`, %95 bootstrap GA ile.
Kırılımda **yalnız hedeflenen metrik** sayılır — konu dışı bir cevap bağlama sadık
(faithful) *olabilir*; faithfulness'ı `off_topic` kırılımına yazmak hakemi haksız
yere suçlardı.

- Kod: `src/eval/judge_control.py`, CLI `src/eval/judge_control_cli.py`
- Testler: `tests/unit/test_judge_control.py` (21 test)
- Veri: `tests/golden/golden_10biy_v2.json` (225 item, 10/biyoloji)
- Hakem modeli: `deepseek-chat` · Koşum: 244,2 s · Hata: 0

---

## BULGU 0 (koşumun ilk çıktısı) — hakem **hiç çalışmıyordu**

Kontrol koşumunun ilk denemesinde **60 ölçümün 60'ı** şu hatayla düştü:

```
AttributeError: 'str' object has no attribute 'truths'
AttributeError: 'str' object has no attribute 'statements'
AttributeError: 'str' object has no attribute 'steps'
```

`DeepSeekJudgeModel.generate()` her koşulda `str` döndürüyordu. deepeval 2.9.3'te
`schema=` verilen çağrı **o şemanın nesnesini** bekliyor. Yani hakem hiç
çalışmıyordu.

**Bu neden görünmüyordu:** `LlmJudge.evaluate()` istisnayı `errors` listesine yazıp
`None` skor döndürüyor, rapor da `None`'ları atlıyordu. Hakem sessizce hiçbir şey
ölçmüyor, hiçbir yerde "ölçemedim" demiyordu. Negatif kontrol suite'inin var oluş
sebebi tam olarak budur.

**Düzeltme:** `_parse_schema()` — çıktı JSON'a çevrilip şema nesnesi kurulur; kod
bloğu sarmalı ve çevresindeki serbest metin kırpılır. Çözülemeyen çıktı **istisna
atar**, sessizce boş nesneye dönüşmez (pass-bias yasak).

---

## BULGU 1 — `faithfulness` uydurmaya KÖR

Hakem tamir edildikten sonra ölçülen ilk tablo:

| metrik | pozitif | negatif | **ayrım** |
|---|---|---|---|
| faithfulness | 1,000 | 0,980 | **0,020** |
| answer_relevancy | 0,812 | 0,463 | 0,348 |
| answer_correctness | 1,000 | 0,280 | 0,720 |

`fabricated_fact` vakalarında faithfulness = **1,000**. Yani gold cevabın içine
*"Bu konu ilk kez 1923 yılında Ankara'da bir laboratuvarda kanıtlanmıştır."*
cümlesi eklendiğinde hakem cevabı **tamamen sadık** buluyor.

**Neden:** DeepEval'in `FaithfulnessMetric`'i yalnız bağlamla **ÇELİŞEN** iddiaları
cezalandırır. Bağlamda geçmeyen ama çelişmeyen bir iddia tam puan alır. Bu metriğin
tanımı gereğidir, bir kusuru değildir — **bizim tanımımızla uyuşmamasıdır**: bu üründe
"uydurma", çelişmek değil **desteksiz olmak**tır.

Ürün açısından: RAG'in en kritik hata türü uydurmadır ve ana metriği ona kördü.

---

## BULGU 2 — BOŞ cevap üç metriğin ikisinde tam puan

`empty` vakalarında `faithfulness = 1` ve `answer_relevancy = 1`. Hiçbir şey
söylemeyen bir cevap "mükemmel" ölçülüyordu.

---

## BULGU 3 — tersine çevrilmiş iddia neredeyse cezasız

`negation` vakalarında `answer_correctness = 0,9`. Gold'daki "artar" → "azalır"
çevrildiğinde skor 1,0'dan yalnız 0,1 düşüyordu. Öğrenciye **yanlış öğretilen** bir
olgu, eksik öğretilenden daha zararlıdır; ölçü bunu yansıtmıyordu.

---

## Düzeltmeler

1. **`_parse_schema()`** — deepeval şema sözleşmesi (BULGU 0).
2. **Yeni `groundedness` metriği** (GEval, `ACTUAL_OUTPUT` × `RETRIEVAL_CONTEXT`):
   "bağlamda karşılığı bulunmayan her ek iddia puanı ciddi biçimde düşürür — bağlamla
   çelişmese bile". `faithfulness` **kaldırılmadı**: çelişki ile desteksizlik farklı
   şeylerdir, ikisi de raporlanır ki fark görünür kalsın.
3. **Boş cevap kısa devresi** — LLM'e hiç sorulmaz, dört metrik de 0,0
   (`reason="cevap bos"`). Ayrıca bedava değildi.
4. **Daha katı correctness kriteri** — yön tersine çevrilmişse ("artar/azalır",
   "vardır/yoktur", "üretir/tüketir") cevabın geri kalanı doğru olsa bile 0,2'nin
   altında puan.

---

## Sonuç (düzeltme sonrası, aynı 20 vaka)

| metrik | pozitif (GA %95) | negatif (GA %95) | **ayrım** |
|---|---|---|---|
| faithfulness | 1,000 [1,000–1,000] | 0,780 [0,500–1,000] | 0,220 |
| **groundedness** | 0,900 [0,700–1,000] | 0,095 [0,000–0,275] | **0,805** |
| answer_relevancy | 0,812 [0,585–0,983] | 0,263 [0,043–0,507] | 0,548 |
| answer_correctness | 1,000 [1,000–1,000] | 0,160 [0,000–0,390] | 0,840 |

Bozma türü kırılımı (yalnız hedeflenen metrik):

| bozma türü | metrik | önce | sonra |
|---|---|---|---|
| `fabricated_fact` | faithfulness | 1,000 | 1,000 *(değişmedi — tanımı gereği)* |
| `fabricated_fact` | **groundedness** | — | **0,025** |
| `negation` | answer_correctness | 0,900 | **0,000** |
| `empty` | answer_relevancy | 1,000 | **0,000** |
| `off_topic` | answer_relevancy | 0,000 | 0,000 |
| `evasive` | answer_relevancy | 0,000 | 0,000 |
| `verbatim_gold` (pozitif) | groundedness | — | 0,900 |

---

## Dürüst sınırlar (kapatılmadı)

1. **Üretici ile hakem hâlâ AYNI MODEL** (`deepseek-chat`) → self-preference riski
   ölçülmedi. `--judge-model` bayrağı hazır; EXP-009'daki `nemotron-3-super` adayıyla
   tekrar koşulmalı ve iki hakem karşılaştırılmalı. **#72 bu yüzden kapanmaz.**
2. **Cohen κ hesaplanmadı** — insan etiketi yok. `cohen_kappa()` yazıldı ve test
   edildi; TAM kapısı κ ≥ 0,75 için 60–150 insan etiketi gerekiyor (#91).
3. **`answer_relevancy` pozitif = 0,812** — gold cevabın *kendisi* yalnız 0,81
   "ilgili" bulunuyor. Ders kitabı pasajları soru-cevap biçiminde yazılmadığı için
   beklenen bir sonuç olabilir, ama **doğrulanmadı**. Bu metriğin eşiği bu tavan
   bilinmeden konamaz.
4. **n = 20** dar. GA'lar geniş (ör. negatif faithfulness [0,500–1,000]). Eşik
   kararları bu koşuma dayandırılmamalı.
5. Kontrol vakaları **sentetik**: gerçek ürün çıktısındaki hatalar bunlardan farklı
   görünebilir. Gerçek çıktılar üzerinde insan etiketi hâlâ gerekli.

## Ham çıktı

- `tests/evaluation/results/judge_control_20260913T020632Z.json` (düzeltme sonrası)
- `tests/evaluation/results/judge_control_20260913T020032Z.json` (düzeltme öncesi)
- `tests/evaluation/results/judge_control_20260913T015600Z.json` (BULGU 0: 60/60 hata)

## Kadir'in doldurması gereken alanlar

| Soru | Karar |
|---|---|
| `groundedness` ana uydurma metriği olarak kabul mu? | |
| `faithfulness` raporda kalsın mı, yoksa yanıltıcı mı? | |
| Hakem modeli üreticiden farklı olmalı mı (maliyet ↑)? | |
| `answer_relevancy` 0,812 tavanı kabul edilebilir mi? | |
| n=20 yeterli mi, 60'a çıkarılsın mı? | |

**Nihai durum: `İNSAN İNCELEMESİ BEKLİYOR`.**
