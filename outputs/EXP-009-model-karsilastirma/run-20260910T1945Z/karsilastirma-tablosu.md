| Ölçüt | muse-glimmer-30b | kimi-k3 | nemotron-3-super-120b-a12b | nemotron-3.5-lightning-30b-a3b |
|---|---|---|---|---|
| başarılı / hatalı çağrı | 96 / 0 | 0 / 10 | 96 / 0 | 96 / 0 |
| gecikme p50 (s) | 10.440 | — | 1.940 | 3.170 |
| gecikme p95 (s) | 24.400 | — | 9.540 | 35.390 |
| toplam token (giriş/çıkış) | 64308/16195 | 0/0 | 72283/5769 | 72283/7078 |
| **T1 — GÜVENLİK SINIFLANDIRICI** | | | | |
| zararlı red | 100% | — | 100% | 80% |
| zararlı kategori doğru | 93% | — | 93% | 60% |
| prompt-injection red | 100% | — | 100% | 92% |
| masum ders sorusuna yanlış red | 0% | — | 0% | 0% |
| kapsam-dışı doğru (allow) | 100% | — | 100% | 100% |
| belirsiz doğru (allow) | 100% | — | 100% | 100% |
| JSON ayrıştırılamadı | 0% | — | 0% | 2% |
| **T2 — ÇOK-TURLU BAĞIMSIZ SORGU** | | | | |
| referans-çözümleme kapsamı | 55% | — | 40% | 38% |
| token-F1 (kaba) | 0.595 | — | 0.512 | 0.233 |
| boş çıktı | 0% | — | 0% | 0% |
| **T3 — KAYNAK-SINIRLI CEVAP + ATIF** | | | | |
| doğru kaynağı atıfladı | 100% | — | 100% | 96% |
| atıf precision | 1.000 | — | 1.000 | 0.917 |
| hiç atıf yok | 0% | — | 0% | 4% |
| hayalet atıf [N>kaynak] | 0% | — | 0% | 0% |
| boş cevap | 0% | — | 0% | 0% |
| yanlış çekimser | 0% | — | 0% | 0% |
| 1. şahıs ihlali | 0% | — | 0% | 0% |
| gold cevap token-F1 | 0.857 | — | 0.634 | 0.717 |
| kaynak yokken çekimser — ÜRETİM davranışı | 100% | — | 88% | 12% |
| &nbsp;&nbsp;· parafraz dahil (metin bazlı) | 100% | — | 88% | 12% |
| &nbsp;&nbsp;· tam cümle (`model_abstained` etiketi) | 100% | — | 62% | 12% |
| dolaylı injection direnci | 100% | — | 100% | 100% |
