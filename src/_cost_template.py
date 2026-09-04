"""Maliyet.md profesyonel iskeleti. costlog.render() AUTO bloklarını doldurur;
manuel bölümler (ilkeler, tanımlar, bütçe projeksiyonu) korunur.

Not: Dosya adı İngilizce (kod dosyalarında Türkçe ad yok); içerik ürün dili Türkçe."""

TEMPLATE = r"""# 💸 RAG Maliyet Defteri

> **Amaç:** Her denemenin (run) maliyetini **adım adım, tek yerde, karışıklık
> olmadan** tutmak. Böylece "bu modülün birim maliyeti ne?", "10 özet kaç para?",
> "neyi değiştirince maliyet arttı?" sorularının kanıtlı cevabı olur ve ürüne
> geçerken maliyet **gerçek verilerle** hesaplanır.
>
> İlgili: [[deney-sonuclari]] (kalite/DeepEval) · [[gorevler]] · [[README]]

<!-- AUTO:STAMP:START -->
<!-- AUTO:STAMP:END -->

## 📏 Metot (değişmez kurallar — kafa karışıklığını önler)
1. **Tek doğruluk kaynağı = `runs.jsonl`** (append-only). Bu dosya (Maliyet.md) o
   kayıttan **otomatik üretilir**; aşağıdaki `AUTO` blokları elle düzenlenmez.
2. **Her LLM işi bir "run"**: hangi modül, hangi model, kaç token, **maliyet**,
   **birim maliyet** (maliyet ÷ adet) ve **"ne değişti → maliyet etkisi"** notu.
3. **Birim maliyet üründe konuşulan sayıdır** (ör. "1 özet = \$X", "1000 özet = \$Y").
4. **Kalite ile birlikte okunur**: maliyet tek başına anlamsız; ucuz ama yanlış
   modül işe yaramaz. Kalite skorları [[deney-sonuclari]]'nda; buradaki her run
   opsiyonel `quality` alanıyla oraya bağlanır.
5. **Fiyat değişince yalnız `src/pricing.py` güncellenir**; tablo otomatik yansır.
6. **Canlı ölçüm zorunlu**: her DeepSeek çağrısında API'nin döndürdüğü `usage`
   (cache-hit/miss, çıkış, reasoning token) okunur ve kaydedilir — tahmin değil
   gerçek token. (RagArt bunu yapmıyordu; bizim ayrım noktamız.)

Kaydı kod otomatik yapar:
```python
from src.costlog import record
record(module="ozet", model="deepseek-chat", usage=result.usage, items=10,
       note="chunk 800→500 → cache arttı, maliyet %12 düştü")
```
Elle yeniden üretmek için: `python -m src.costlog render`.

## 🏷️ Güncel fiyatlar (DeepSeek)
<!-- AUTO:PRICING:START -->
<!-- AUTO:PRICING:END -->

## 🎯 Birim maliyet tanımları (modül başına "adet" nedir)
| Modül | 1 adet = | Neden önemli |
|---|---|---|
| Kaynakla konuşma | 1 kullanıcı sorusuna 1 cevap | Öğrenci başına aylık maliyet tahmini |
| Özet üretimi | 1 konu/parça özeti | Kaynak başına toplu özetleme maliyeti |
| Kaynaktan soru üretimi | 1 onaya hazır soru (ret'ler dahil amortize) | Soru bankası büyütme maliyeti |
| Benzer soru üretimi | 1 varyant soru | Sınav çeşitlendirme maliyeti |
| Embedding | 1000 chunk | İndeksleme tek seferlik maliyeti |

## 📊 Modül birim maliyet özeti (otomatik)
<!-- AUTO:MODULE:START -->
<!-- AUTO:MODULE:END -->

## 🧾 Deney defteri — tüm run'lar (otomatik)
> "Ne değişti → maliyet etkisi" sütunu neden-sonucun kaydıdır. Her satır bir deney.
<!-- AUTO:LEDGER:START -->
<!-- AUTO:LEDGER:END -->

## 🤖 Model karşılaştırması (otomatik)
<!-- AUTO:MODELS:START -->
<!-- AUTO:MODELS:END -->

## 📈 Ürün bütçe projeksiyonu (elle — birim maliyet ölçülünce doldur)
> Birim maliyet defterden (yukarıdaki AUTO tablo) **gerçek** değerle gelir; buraya
> ürün varsayımlarını (kullanıcı sayısı, kullanım sıklığı) koyup aylık bütçeyi çıkar.

| Senaryo | Aktif öğrenci | Öğrenci/ay kullanım | Birim maliyet (defterden) | Aylık maliyet ~ | Cache sonrası ~ |
|---|---|---|---|---|---|
| Pilot | 50 | 40 soru + 10 özet | — | — | — |
| Okul | 500 | 40 soru + 10 özet | — | — | — |
| Ölçek | 5.000 | 40 soru + 10 özet | — | — | — |

- **Bütçe eşiği (alarm):** öğrenci başı aylık maliyet > \$… olursa (chunk küçült /
  top-k düşür / cache oranı artır) → etkisini [[deney-sonuclari]] ile doğrula.
- **Cache etkisi:** ResponseCache tekrar sorularda LLM çağrısını **sıfırlar**;
  EmbeddingCache indekslemeyi amortize eder — projeksiyonda "cache sonrası" sütunu bunu yansıtır.

## 🧠 Maliyet düşürme notları (elle)
- **Prompt cache**: aynı bağlam tekrar kullanılıyorsa cache-hit fiyatı ~30× ucuz →
  few-shot örnekleri ve sistem promptunu sabit tut.
- **Off-peak**: toplu işleri (indeksleme, toplu özet) indirimli pencerede koştur.
- **Model seçimi**: kolay işte `flash`, zor akıl-yürütmede `pro`; her modülde ayrı ölç.
- **Reranking/az top-k**: bağlamı kısaltmak giriş token'ını (maliyeti) düşürür —
  ama kaliteyi [[deney-sonuclari]]'ndan izle, ucuza kaliteyi feda etme.
"""
