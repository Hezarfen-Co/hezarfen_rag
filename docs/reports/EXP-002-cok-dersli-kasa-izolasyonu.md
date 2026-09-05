# EXP-002 — Çok-dersli ölçek + kasa izolasyonu (ders + sınıf boyutu)

- **Tarih:** 2026-09-06
- **Commit (kod):** `3691ee8`
- **Ortam:** Windows 11, RTX 4060, `.venv` (torch cu124 GPU), BGE-M3 (embed) + BGE-reranker-v2-m3 (rerank), DeepSeek (yalnız T2 üretimi).
- **Veri sürümü:** golden `golden_12bio_v1.json` (v1.1, 200 item TASLAK — Kadir onayı bekliyor); korpus EBA ders kitapları.
- **Ham çıktı:** `scratchpad/exp004_multisubject.py`, `scratchpad/exp004b_crossgrade.py` (çalıştırma logları oturum task dosyalarında).
- **Amaç:** Kasa izolasyonu tek-ders/sentetik ötesinde, **gerçek çok-kitaplı indekste** tutuyor mu? İkincil: ölçek retrieval'i bozuyor mu?
- **İlke (bağlayıcı):** pass-bias YOK — amaç sızıntıyı/zaafı görmek.

## 1. Kurulum
İki bağımsız birleşik indeks (her chunk meta = `{sinif, ders}`; `HybridRetriever(meta=)` → RRF sonrası `can_access` filtresi):

| İndeks | Kitaplar | Child chunk |
|---|---|---|
| A (ders boyutu) | 12-biyoloji + 12-kimya + 12-fizik | 258 + 221 + 445 = **924** |
| B (sınıf boyutu) | 12-biyoloji + 11-biyoloji | 258 + 309 = **567** |

Sorgu kümesi: golden'dan 40 biyoloji "cevapla" sorusu (gold_sayfalar'lı). Rol: `student / sınıf=12 / ders_list=["biyoloji"]` (sunucu-tarafı).

## 2. Sonuçlar

### T1 — Çapraz-DERS sızıntı (indeks A, bio-only öğrenci)
| Ölçüt | Değer |
|---|---|
| İzolasyonlu top-20'de yabancı (kimya/fizik) chunk | **0 / 800** |
| Test gücü: izolasyonSUZ yüzeye çıkan yabancı chunk | **66** |

→ Hibrit retrieval, filtre olmasa 66 kimya/fizik chunk'ı getiriyordu (komşu fenler semantik yakın); **hepsi** engellendi.

### S1 — Çapraz-SINIF sızıntı (indeks B, en zor vaka: aynı ders farklı sınıf)
| Ölçüt | Değer |
|---|---|
| İzolasyonlu top-20'de `sınıf=11` chunk | **0 / 800** |
| Test gücü: filtresiz yüzeye çıkan 11-bio chunk | **63** |

→ Aynı ders = maksimum semantik benzerlik; filtresiz 63 chunk çıkarken hepsi engellendi. `can_access`'in `sinif != sinif` dalı gerçek retrieval'la doğrulandı.

### T2 — Başka-ders erişim denemesi (bio-only öğrenci kimya/fizik sorusu sorar)
| Sorgu | İzinli chunk | Yabancı sızıntı | Generator |
|---|---|---|---|
| kimya ×2 | 10, 20 | 0, 0 | abstain ✓ |
| fizik ×2 | 12, 8 | 0, 0 | abstain ✓ |

→ **4/4** sıfır yabancı sızıntı + fail-closed çekimser. Doğru ürün davranışı (öğrenci yetkisiz derse ulaşamaz, sistem kaynak uydurmaz).

### T3 — Genelleştirme / distraktör (indeks A, bio sayfa-recall@20)
| Koşul | recall@20 |
|---|---|
| İzolasyonlu | 1.000 (n=40) |
| İzolasyonsuz (distraktörlü) | 1.000 |

## 3. Bulgular (dürüst)
- **[DENEYSEL SONUÇ] Kasa izolasyonu çok-kitaplı ölçekte SAĞLAM** — hem **ders** hem **sınıf** boyutunda gerçek retrieval'la 0 sızıntı; toplam **129 yabancı chunk** (66+63) filtresiz gelirdi, hepsi engellendi. Önceki 0-sızıntı tek-ders/sentetikti; bu, 4 gerçek kitapla (komşu fenler + çapraz-sınıf aynı ders) güçlendirilmiş kanıttır.
- **[DENEYSEL SONUÇ] Ölçek retrieval'i gözle görülür bozmadı** — bio recall distraktörlerle düşmedi.
- **[ZAAF — metrik] T3 doygun:** sayfa-recall@20 tavanda (1.000) ve izolasyonlu=izolasyonsuz; **bu metrik küçük bozulmayı algılayamaz** (sayfa-granülerliği cömert). "Bozulma yok" iddiası bu metrikle ZAYIF kanıtlıdır. → Öneri: span-seviyesi recall veya zor-negatif (hard-negative) sorgularla ayırt edici ölçüm (backlog).
- **[VARSAYIM] Kapsam sınırı:** yalnız biyoloji sorgu kümesi var (golden bio-only); kimya/fizik/11-bio için gold yok → onların retrieval kalitesi ölçülmedi, yalnız izolasyon/distraktör rolünde kullanıldılar.

## 4. Aksiyon
- Kasa izolasyonu maddesi: çok-dersli ölçekte **DOĞRULANDI** (OPTIMIZATION §H + PROJECT_STATE güncellenir).
- Backlog: ayırt edici retrieval metriği (span-recall / hard-negative) — T3 doygunluğunu aşmak için.
- Durum: `İNSAN İNCELEMESİ BEKLİYOR` (nihai kabul Kadir).
