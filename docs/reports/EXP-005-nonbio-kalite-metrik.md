# EXP-005 — Non-bio kalite (kimya+fizik) + ayırt edici retrieval metriği (#24)

- **Tarih:** 2026-09-06
- **Commit:** gold `92f53bb`; ölçüm `scratchpad/exp005_nonbio_eval.py`.
- **Veri:** `tests/golden/golden_12kimya_v1.json` (31 item), `golden_12fizik_v1.json` (30 item) — **TASLAK, Kadir onayı bekliyor** (benchmark-lock). cevapla item'lar gerçek kaynak pasajlarından türetildi (gold objektif), insan-curate (künye/içindekiler/cevabı-metinde-olmayan elendi).
- **Amaç:** (a) EXP-002'de doygun çıkan sayfa-recall@20 yerine **ayırt edici metrik**; (b) non-bio derslerin retrieval+üretim+guardrail KALİTESİ (şimdiye dek yalnız izolasyon rolündeydiler). İlke: pass-bias YOK.

## 1. Sonuçlar

| Metrik | kimya (n=23 cevapla) | fizik (n=22) | bio baseline (v1.1) |
|---|---|---|---|
| retrieval recall@5 | 0.913 | 0.955 | — |
| recall@10 | 0.978 | 0.955 | — |
| recall@20 | 1.000 | 0.977 | 0.97 (sayfa) |
| **MRR** | 0.864 | 0.955 | 0.811 |
| üretim abstain (yanlış-çekimser) | **0/23** | **0/22** | ~0 |
| citation sayfa P / R | 0.612 / 0.783 | 0.739 / 0.864 | 0.645 / 0.883 |
| guardrail red reddedildi | **3/3** | **3/3** | 33/33 |
| çekimser abstain | **5/5** | **5/5** | 22/22 |

## 2. Bulgular (dürüst)
- **[DENEYSEL SONUÇ] (a) Ayırt edici metrik ÇÖZÜLDÜ.** recall@5/@10 + MRR **doygun DEĞİL** (kimya @5=0.913, fizik @20=0.977, MRR 0.864/0.955) — EXP-002'de doygun çıkan sayfa-recall@20'nin aksine gerçek sinyal veriyorlar. Bundan sonra retrieval değerlendirmesinde **recall@5/@10 + MRR** birincil.
- **[DENEYSEL SONUÇ] (b) RAG dersler arası GENELLEŞİYOR (bio-overfit DEĞİL).** kimya/fizik retrieval bio ile aynı/daha iyi (MRR fizik 0.955 > bio 0.811); üretimde **0 yanlış-çekimser** (cevaplanabilir non-bio soruların hepsi cevaplandı); citation P/R bio bandında (fizik daha iyi). Bu, ürün-hazırlık için kritik bir sinyal: boru hattı tek-derse özel değil.
- **[DENEYSEL SONUÇ] Guardrail domain-yakın zararlıyı yakalıyor.** kimya "uyuşturucu/patlayıcı sentezi", fizik "nükleer silah/elektrik tuzağı" — konuya yakın olmalarına rağmen **3/3 reddedildi**; kapsam-dışı sorular 5/5 çekimser. Bir kimya RAG'inin uyuşturucu-sentezini reddetmesi kritik güvenlik davranışıdır ✓.
- **[SINIR] citation-precision** bio'daki gibi dar-gold tanımından sınırlı (model komşu ilgili sayfayı da atıflıyor) — model over-citation'ı değil (bkz. OPTIMIZATION §H madde 1). kimya P=0.612 biraz düşük; gold genişletilirse artar.
- **[VARSAYIM] Gold inşa yöntemi:** soru kaynaktan türetildi → gold objektif, retrieval-bağımsız; ama sorular DeepSeek-taslak (insan-curate). Soru kalitesi/çeşitliliği insan-yazımı kadar zengin olmayabilir; onay öncesi Kadir gözden geçirmeli.

## 3. Aksiyon
- #24: **çözüldü** — (a) ayırt edici metrik OPTIMIZATION'a standing karar; (b) non-bio kalite ölçüldü + genelleşme kanıtlı.
- **Kadir onayı bekleyen:** kimya+fizik gold TASLAK (bio v1.1 ile birlikte).
- Ürün-hazırlık checklist'ine katkı: chat düzgün (0 yanlış-çekimser, guardrail sağlam) + çok-ders retrieval güçlü. Kalan: özet çok-ders, multimodal tam-korpus, servis → sonra 10k benchmark (#25).
- Durum: `İNSAN İNCELEMESİ BEKLİYOR`.
