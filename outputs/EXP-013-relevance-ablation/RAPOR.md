# EXP-013 — Çeşitlilik kısıtı → ilgililik eşiği ablation'ı (#59)

**Tarih:** 2026-09-12 · **Durum:** `İNSAN İNCELEMESİ BEKLİYOR`
**Kitap:** `data/lise/10/biyoloji/kitap.pdf` · **Tohum:** 20260912
**Sorgu:** 120 aynı-parent + 120 farklı-parent çifti · **top_n:** 6 · GPU

## 0. Karar ve gerekçe

Kadir (2026-09-12): *"birden fazla kanıt getirebilir, 2'den de fazla olabilir,
konuyla ilgiliyse — ama **ilgili olması lazım**."*

Bu, ölçütü değiştirdi: doğru soru "kaç chunk aynı parent'tan geldi" değil,
**"ilgili mi"**. Yapısal kısıt (`per_parent`) yerine ilgililik eşiği kondu:

```
score >= max(RELEVANCE_MIN = 0.05, tepe_skor × RELEVANCE_REL = 0.10)
```

Eşik tahminle değil **veriden** seçildi (aynı kitap, 23 gerçek sorgu, top-40):

| sıra | medyan skor |
|---|---|
| tüm adaylar | **0,006** (p90 = 0,619) |
| 1. sıradaki | 0,848 |
| 2. sıradaki | 0,621 |
| 10. sıradaki | 0,128 |

Dağılım **iki kutuplu**: ilgili olan yüksek, alakasız ~0 alıyor. Göreli parça
şart çünkü tepe skor sorguya göre 0,0025–0,9999 arasında değişiyor; mutlak
parça da şart çünkü göreli eşik tek başınayken çöp adaylar tepeye göre yüksek
görünebilir.

## 1. Sonuç — iki yönde

| kural | yön | all_evidence_recall | kısmi | hiç | seçilen | **ilgisiz oran** | sayfa |
|---|---|---|---|---|---|---|---|
| **eski** (yapısal) | aynı-parent | **0,000** | 0,875 | 0,125 | 6,00 | 0,119 | 5,89 |
| eski | farklı-parent | 0,167 | 0,667 | 0,167 | 6,00 | 0,093 | 5,91 |
| **yeni** (ilgililik) | aynı-parent | **0,458** | 0,508 | 0,033 | 5,52 | **0,000** | 4,80 |
| yeni | farklı-parent | 0,150 | 0,783 | **0,067** | 5,58 | **0,000** | 5,03 |
| eşik yok (saf skor) | aynı-parent | 0,483 | 0,492 | 0,025 | 6,00 | 0,074 | 5,19 |
| eşik yok | farklı-parent | 0,150 | 0,783 | 0,067 | 6,00 | 0,065 | 5,42 |

%95 Wilson güven aralıkları (aynı-parent, n=120):

| | oran | %95 GA |
|---|---|---|
| eski | 0/120 = 0,000 | [0,000 – 0,031] |
| yeni | 55/120 = 0,458 | [0,372 – 0,547] |
| eşik yok | 58/120 = 0,483 | [0,396 – 0,572] |

## 2. Okunuşu

1. **Eski kural aynı-parent'ta tamamen kördü.** 120 sorgunun hiçbirinde iki
   kanıtı birlikte getirmedi; %95 GA üst sınırı 0,031. Bu bir ayar sorunu
   değil, kuralın kendisiydi.
2. **Yeni kural bunu 0,458'e çıkardı** ve aralıklar örtüşmüyor → gerçek fark.
3. **Farklı-parent'ta zarar yok.** 0,167 → 0,150 (20 → 18 item); GA'lar geniş
   ölçüde örtüşüyor, bu bir fark değil **gürültü**. Buna karşılık "hiçbirini
   bulamadı" oranı **0,167 → 0,067** düştü.
4. **İlgililik şartı tutuyor.** Seçilenlerin ilgisiz oranı **0,119 → 0,000**.
   Kadir'in koyduğu şart ölçülebilir biçimde sağlanıyor.
5. **Eşiğin bedeli küçük, kazancı net.** Eşik yok'a göre aynı-parent recall
   0,483 → 0,458 (GA'lar örtüşüyor), buna karşılık ilgisiz oran 0,074 → 0,000,
   bağlam 6,00 → 5,52 chunk ve kapsanan sayfa 5,19 → 4,80. Yani daha az ve
   daha temiz bağlam; token maliyeti de düşüyor.

## 3. Kendi aleyhimize

* **Golden set ölçümü DEĞİL.** 12. sınıf ders kitabı hâlâ yok (#92); bu bir
  "çift-iğne" vekilidir: iki komşu birimin metninden sorgu kurulur.
* **Vekil yanlıdır.** Aynı-parent kümesi yapı gereği aynı-parent'ı ödüllendirir;
  bu yüzden karşı yön (farklı-parent) ayrıca ölçüldü — asıl kanıt odur.
* **Mutlak değerler düşük.** 0,458 iyi bir kapı değeri değil; kapı **K-06**
  çok-span recall@20 ≥0,90 istiyor ve bu ölçüm top_n=6'da. Yön doğru, seviye
  yetersiz — kalan açık golden set üzerinde kapatılmalı.
* n=120; ±0,09 civarı bir belirsizlik var.

## 4. Yan etki: `top_n` artık kota değil

Eski kod yuvaları doldurmak için son çare olarak kısıtı gevşetip skoru ~0
chunk'ları da alıyordu. Ölçümde bu, seçilenlerin **%11,9'unun ilgisiz** olması
demekti. Artık dolgu da mutlak tabanı geçmek zorunda; `top_n` bir üst sınır.

## 5. Yeniden üretim

```
.venv/bin/python outputs/EXP-013-relevance-ablation/ablation.py OUT.json
```
Ham çıktı: `sonuc.json` · koşum kaydı: `kosum.log`
