# EXP-011 — Sayfa hizalı chunk'lama ablation'ı (#53)

**Tarih:** 2026-09-11 · **Durum:** `İNSAN İNCELEMESİ BEKLİYOR`
**Kitap:** `data/lise/10/biyoloji/kitap.pdf` (194 sayfa, 3301 birim, 3096 retrievable)
**Donanım:** RTX 4060 Laptop 8 GB, CUDA 13.0, torch 2.14.0+cu130
**Tohum:** 20260911 · **Sorgu sayısı:** 200 (her iki yapılandırmada **aynı** sorgular)

## 0. Neden

`generator.py` atıfı chunk düzeyinde üretiyor:
`citations[i].pages = _pages_for_span_ids(ctx.span_ids)`. Yani bir atıf, chunk'ın
**tüm** span'larının sayfalarını taşır. Child chunk'lar sayfa sınırını serbestçe
aştığı için her aşan chunk atıfa **fazladan sayfa** ekliyordu.

Denetimde (EXP-010/ACC-02) hesaplanan tavan: `precision_page ≤ min(1, gold/cited)`.

## 1. Yapısal ölçüm (kesin, örneklemsiz)

| | eski (serbest) | yeni (sayfa hizalı) |
|---|---|---|
| child chunk | 232 | **327** (+%41) |
| parent chunk | 63 | 64 |
| sayfa aşan child | **147 (%63,4)** | **0 (%0)** |
| chunk başına ort. sayfa | 1,716 | **1,000** |
| `precision_page` teorik tavanı | **0,723** | **1,000** |
| token ort. / medyan | 258,1 / 258,5 | 183,2 / 203 |
| token p10 | 180,2 | **37,6** |
| <150 token chunk | 1 | **107** |
| <50 token chunk | 0 | **43 (%13,1)** |

Kapı G/A-* için kritik olan satır sonuncudan üçüncüsü: **0,99'luk sayfa-atıf
kapısı eski chunk'lamayla matematiksel olarak ulaşılamazdı.** Daha büyük bir
embedding modeli bunu düzeltmezdi.

## 2. Retrieval ablation'ı — **VEKİL**, kapı ölçümü DEĞİL

> **Dürüst sınır.** Golden set 12. sınıf `doc_id`'lerine bağlı ve `data/lise/12`
> depoda yok (**#92 ENGEL**). Bu yüzden gerçek kapı ölçümü koşulamadı. Burada
> "needle" vekili kullanıldı: kitaptan seçilen bir birimin kendi metni sorgu,
> gold = o span'ı içeren chunk. Sorgu↔gold sözcük örtüşmesi yüksek olduğu için
> **mutlak sayılar gerçek sorulardan kolaydır**; ama iki yapılandırma aynı
> sorgular, aynı tohum ve aynı boru hattıyla ölçüldüğü için **fark** anlamlıdır.
> İkinci bir sorgu kümesi (birimin yalnız ilk yarısı) örtüşmeyi kırmak için
> koşuldu.

| metrik | eski (tam) | yeni (tam) | eski (yarım) | yeni (yarım) |
|---|---|---|---|---|
| recall@5 | 0,995 | 0,995 | 0,990 | **0,995** |
| recall@10 | 0,995 | 0,995 | 0,995 | 0,995 |
| recall@20 | 1,000 | 1,000 | 1,000 | 1,000 |
| MRR | 0,9562 | **0,9761** | 0,9487 | **0,9635** |
| top-1 sayfa precision | 0,6467 | **0,9700** | 0,6433 | **0,9450** |
| top-1 sayfa isabeti | 0,945 | 0,970 | 0,940 | 0,945 |

**#53'ün kabul kriteri** ("`precision_page` yükselmeli **VE** recall düşmemeli")
bu vekilde **sağlanıyor**: sayfa hassasiyeti +0,32 (bağıl +%50), recall
değişmedi, MRR hafif yükseldi.

### 2.1 Bu kanıtın zayıf yanı (kendi aleyhimize)

Recall bu vekilde **tavana dayalı** (0,995–1,000). Tavana dayalı bir metrik
**bozulmayı göremez**: "recall düşmedi" ifadesi burada güçlü bir kanıt değil,
yalnızca "bu kolay kümede düşmedi" demektir. Gerçek karar golden set'e aittir.

## 3. Bayrak edilen riskin doğrudan ölçümü

Sayfa hizalama küçük parçalar üretiyor (43 chunk < 50 token). Bunlar top-k
yuvalarını işgal edip bağlamı fakirleştirir mi?

| | eski | yeni |
|---|---|---|
| korpusta <50 token | 0 (%0) | 43 (**%13,1**) |
| top-5'te <50 token ort. yuva | 0 | **0,09** |
| en az bir minik parça gören sorgu | %0 | **%9** |
| **top-5 toplam token (ort.)** | **1331,1** | **1110,3 (−%16,6)** |
| farklı minik chunk top-5'e girdi | 0 | 12 |

**Sonuç:** yuva işgali beklenenden küçük (sorgu başına 0,09 yuva). Ama **bağlam
hacmi %16,6 düştü** — bu gerçek bir bedel: üretici modele giden kanıt azalıyor.
Minik chunk'lar aslında "içinde az metin olan sayfalar" (şekil sayfası, bölüm
kapağı); küçük olmaları doğru, sorun onların varlığı değil **toplam bağlamın
azalması**.

## 4. Karar ve açık kalemler

- **Öneri:** sayfa hizalama açık (`RAG_CHUNK_PAGE_ALIGNED=1`, varsayılan).
  Gerekçe: ulaşılamaz bir kapıyı ulaşılabilir yapıyor, vekilde recall bedeli yok.
- **Kapı kararı verilmedi.** #53'ün kabulü golden set ablation'ına bağlı → **#92**
  çözülmeden kapatılamaz.
- **Yeni açık kalem:** `top_n` yeniden kalibre edilmeli — sabit `top_n=6` ile
  bağlam %16,6 daraldı. Bu, çekimserlik eşiği kalibrasyonuyla (#60) birlikte
  ölçülmeli; tek başına `top_n`'i büyütmek maliyeti ve Lost-in-the-Middle riskini
  artırır.
- Eski davranış tek anahtarla geri alınabilir; eval ve üretim **aynı** anahtarı
  okur (ACC-10 dersi).

## 5. Yeniden üretim

```
.venv/bin/python outputs/EXP-011-chunk-ablation/ablation_chunk.py       # yapısal
.venv/bin/python outputs/EXP-011-chunk-ablation/ablation_retrieval.py OUT.json
.venv/bin/python outputs/EXP-011-chunk-ablation/ablation_slot.py OUT.json
```
Ham çıktılar: `ablation_yapisal.json`, `ablation_retrieval.json`, `ablation_slot.json`.
