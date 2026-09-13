# EXP-018 — CPU'da rerank gecikmesi ve reranker'ın kalite katkısı

**Tür:** DENEY · **Tarih:** 2026-09-13 · **Commit:** `124805e`
**İlgili:** #96 (EXP-015'te açıldı) · **Durum:** `İNSAN İNCELEMESİ BEKLİYOR`

## Amaç

EXP-015'te konteyner gerçekten koşuldu ve şu ölçüldü: 40 adaylık rerank
**CPU'da 65,2 s**, GPU'da 1,9 s (**34×**). Uçtan uca 96 s ve 5,6 s. Kapı
**O-05** p50 ≤ 6 s istiyor. Yani konteyner CPU'da **interaktif değil** — okul
demosunda öğrenci bir buçuk dakika bekler.

İki soru: (1) hızlandırma parametreleri ne kadar yer açıyor, (2) hızlandırmanın
kalite bedeli ne?

## BULGU 1 — CPU gecikme ızgarası

3 sorgu ortalaması, `bge-reranker-v2-m3`, CUDA kapalı:

| max_length \ aday | 40 | 20 | 12 | 8 |
|---|---|---|---|---|
| **512** *(bugünkü)* | **95,9 s** | 52,5 s | 32,2 s | 21,3 s |
| 256 | 47,6 s | 25,6 s | 12,1 s | 9,2 s |
| 192 | 37,2 s | 15,7 s | 9,0 s | **6,1 s** |

*(512/40 burada 95,9 s; EXP-015'te 65,2 s ölçülmüştü. Fark makine yükü —
ölçüm sırasında başka iş koşuyordu. Büyüklük mertebesi aynı.)*

**En agresif ayar (192/8) tek başına 6,1 s** — kapının bütün bütçesi. Geriye
retrieval, LLM çağrısı ve guard için **sıfır** kalıyor.

> **Sonuç: CPU'da bu reranker ile O-05 geçilemez.** Parametre ayarı bu duvarı
> aşmıyor, sadece yerini değiştiriyor.

## BULGU 2 — Reranker'ın kalite katkısı bu set ile ÖLÇÜLEMİYOR

"Madem pahalı, kaldıralım mı?" sorusunu ölçmeye çalıştım. İlk ölçüm
reranker'ın **zararlı** olduğunu söyledi:

| yapılandırma | r@6 | r@20 | allev@20 | nDCG@10 |
|---|---|---|---|---|
| RRF (rerank yok) | **0,939** | **0,962** | **0,939** | **0,945** |
| rerank 512/40 | 0,890 | 0,939 | 0,894 | 0,863 |
| rerank 192/40 | 0,875 | 0,924 | 0,894 | 0,872 |

*(66 dev item, aynı aday havuzu, aynı öğe sayısı, ilgililik süzgeci olmadan —
ilk denememde `rerank_select` kullanmıştım, o fonksiyon ilgililik süzgeci
uygulayıp top_n'den az bağlam döndürdüğü için karşılaştırma rerank'e haksızdı.)*

**Bu sonuca güvenmedim** ve senaryo kırılımına baktım:

| senaryo | n | RRF r@6 | rerank r@6 | fark |
|---|---|---|---|---|
| direct | 20 | 1,000 | 0,950 | −0,050 |
| figure_table | 15 | 1,000 | 1,000 | 0,000 |
| synthesis | 10 | 1,000 | 1,000 | 0,000 |
| multi_hop | 10 | 0,950 | 0,700 | **−0,250** |
| **global** | 11 | 0,682 | **0,705** | **+0,023** |

Desen açık ve ölçümün kusurunu ele veriyor: **golden set'in
`direct/synthesis/multi_hop/figure_table` sorguları birimlerin KENDİ
METNİDİR** (iğne testi) — soru değil, metnin kendisi. Lexical + dense
retrieval böyle bir "sorguyu" birebir bulur. Cross-encoder ise
**soru ↔ pasaj** ilgisine bakmak üzere eğitilmiştir; girdisi soru değilse
doğal olarak daha kötü sıralar.

Tek **soru biçimli** kategori olan `global` ("X konusunu anlatır mısın?")
reranker'ın önde olduğu tek kategori — ama n=11 ve fark 0,023 (0,25 item).

> **Ölçüm rerank'in ALEYHİNE yapılandırılmış.** 66 item'ın 55'i iğne testi.
> Bu set "reranker işe yarıyor mu" sorusunu **cevaplayamaz** ve bu sonuca
> dayanarak reranker'ı kaldırmak, ölçüm kusurunu ürün kararına çevirmek olurdu.

## Yapılan değişiklik (tek)

`RAG_RERANK_MAX_LENGTH` eklendi; **varsayılan 512 olarak KALDI**. Amaç, bir CPU
kurulumunun kaliteyi *bilerek* takas edebilmesi — 95 s'ye mahkûm olmak yerine.
Anlamsız değerler (8, 0, −512, 100000) varsayılana düşer: 8 token'lık pasaj
anlamsızdır, 100000 modelin sınırını aşıp çalışma anında patlardı.

## Karar seçenekleri (Kadir)

| Seçenek | Gecikme | Risk |
|---|---|---|
| **A. Demo makinesinde GPU** | 1,9 s rerank, uçtan uca ~5,6 s | Donanım şartı; okulun makinesi belirsiz |
| **B. Daha küçük reranker** (`bge-reranker-base`, ~278M) | ölçülmedi | Türkçe kalite bilinmiyor |
| **C. CPU'da rerank'siz** (yalnız RRF) | ~3 s | Kalite bedeli **bilinmiyor** (bu set ölçemiyor) |
| **D. 192/8'e düş** | 6,1 s *(sadece rerank)* | O-05'i yine geçmez |

**Hiçbiri ölçümle desteklenmiş değil.** B ve C'yi ayırt etmek için
**insan yazımı soru** gerekiyor (#91) — mevcut golden set bu soruyu
cevaplayamaz.

## Kadir'in doldurması gereken alanlar

| Soru | Karar |
|---|---|
| Demo makinesinde GPU olacak mı? (A'yı tek başına çözer) | |
| Yoksa hangi seçenek denensin: küçük reranker mı, rerank'siz mi? | |
| #91'de golden set'e kaç **insan yazımı soru** eklenecek? | |

## Ham çıktı

- Gecikme ızgarası: `outputs/EXP-018-cpu-rerank/cpu_rerank.json`
- Kalite karşılaştırması: `outputs/EXP-018-cpu-rerank/rerank_quality.json`,
  `rq2.json` (ham sıralama), `rq3.json` (senaryo kırılımı)

**Nihai durum: `İNSAN İNCELEMESİ BEKLİYOR`.**
