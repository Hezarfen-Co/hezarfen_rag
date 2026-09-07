# EXP-008 — Measure-after-change re-baseline (denetim + ürün-backlog sonrası)

- **Tarih:** 2026-09-07
- **Amaç:** EXP-007 denetim düzeltmeleri (özellikle #C1 atıfsız→çekimser + guard değişiklikleri) + ürün-backlog (#27 ingest, vb.) kaliteyi BOZDU MU? Measure-after-change disiplini. pass-bias YOK.
- **Yöntem:** DeepEval'siz (bellek-hafif) kendi deterministik metriklerim; kimya golden TASLAK (23 cevapla + 3 red + 5 çekimser) — EXP-005 kimya (denetim ÖNCESİ) ile DOĞRUDAN kıyas.
- **Ham çıktı:** `scratchpad/exp008_rebaseline.py`.

## 1. Kıyas (post-audit vs pre-audit, kimya)
| Metrik | EXP-008 (sonrası) | EXP-005 (öncesi) | Δ |
|---|---|---|---|
| **yanlış-abstain** | **0/23** | **0/23** | **= ✅** |
| cevaplandı | 23/23 | 23/23 | = ✅ |
| guardrail red | 3/3 | 3/3 | = ✅ |
| çekimser abstain | 5/5 | 5/5 | = ✅ |
| recall@5 | 0.848 | 0.913 | -0.065 |
| recall@10 | 0.957 | 0.978 | -0.021 |
| recall@20 | 0.978 | 1.000 | -0.022 |
| MRR | 0.841 | 0.864 | -0.023 |
| citation P/R (sayfa) | 0.558/0.674 | 0.612/0.783 | -0.05/-0.11 |

## 2. Bulgular (dürüst)
- **[DENEYSEL SONUÇ] En riskli değişiklikler GÜVENLİ.** #C1 (geçerli atıf yoksa çekimser) **yanlış-abstain'i ARTIRMADI** (0/23 → 0/23); tüm cevaplanabilir soru hâlâ cevaplandı (23/23). Guardrail (red 3/3, çekimser 5/5) ve fail-closed davranışı bozulmadı. Denetimin ana korkusu (over-abstain / guard regresyonu) gerçekleşmedi.
- **[İZLENECEK] Retrieval/citation'da küçük düşüş** (recall@5 -0.065, citation R -0.11). Kaynağı büyük olasılıkla **#27 ingest değişiklikleri**: LABEL-gate (cümle-noktalamalı kısa blokları artık PARAGRAPH tutuyor → daha çok/küçük chunk) + 2-sütun tam-genişlik yeniden-sıralama → chunk kümesi/sırası değişti → aynı gold sayfaları biraz farklı sıralanıyor. **n=23'te küçük-örneklem gürültüsü bandında** (recall@20 0.978 ≈ 1 item'ın gold'u top-20 dışı). Retrieval sıralama mantığı (embed/rerank) DEĞİŞMEDİ; fark chunk-üretiminden.
- **[VARSAYIM] Gold TASLAK + dar.** citation P/R zaten dar-gold'dan sınırlı (bkz. OPTIMIZATION §H); kimya gold Kadir onayı bekliyor. Kesin karar için onaylı gold + ölçek gerekir.

## 3. Bio full-eval — BELLEK ENGELİ (dürüst)
Bio (122MB) tam eval (200 item, runner) **iki kez exit 127** ile öldü — kök neden **düşük-bellek watchdog**: ölçüm anında yalnız ~3.3 GB boş RAM (chrome ~1.6GB + WSL + claude → %79 dolu); BGE-M3 + BGE-reranker + 122MB parse buna sığmadı. Orphan python YOK, kod sağlam (kimya hafif-parse ile geçti; 419 unit + e2e yeşil). **Çözüm:** bio full-eval, RAM boşaltılınca (chrome kapalı) ya da kalıcı-store/CPU-offload ile üretim ortamında koşulmalı.

## 4. Sonuç / aksiyon
- ✅ **Denetim + özellik değişiklikleri kaliteyi bozmadı** (kritik metrikler sabit); küçük retrieval kayması #27'ye atfedilebilir + gürültü bandında → **regresyon DEĞİL** (onaylı gold + ölçekte doğrulanacak).
- Backlog: onaylı gold + ölçekte re-baseline (#25 yolunda); LABEL-gate'in retrieval'a küçük etkisini izle (gerekirse kısa-blok'a retrieval-ağırlığı düşür).
- Bio full-eval için RAM (chrome-kapalı) ya da üretim ortamı.
- Durum: `İNSAN İNCELEMESİ BEKLİYOR`.
