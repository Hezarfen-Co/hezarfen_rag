# 🏗️ Hezarfen RAG — Mimari Kararı

> Kaynak: [[Literatür/Hezarfen]] (detaylı literatür taraması) + senin kısıtların.
> Bu dosya **NE kuracağız + hangi model/aşama**yı sabitler. Adımlar: [[plan]].
> Kalite kapıları: [[benchmark]]. Kalite kaydı: [[deney-sonuclari]]. Maliyet: [[Maliyet]].
>
> Son güncelleme: 2026-08-29

## 0. Çekirdek karar (literatürden)
> **Uyarlamalı + hibrit + hiyerarşik + (sonra) multimodal RAG.**
Tek başına GraphRAG veya serbest Agentic RAG DEĞİL. Bunlar tamamlayıcı:
- **Hibrit retrieval** (BM25 + dense + neural-sparse) + RRF + **reranker** → varsayılan.
- **RAPTOR** → 187 sayfalık kitap + ünite/kitap özeti (hiyerarşik).
- **Curriculum graph** (deterministik omurga) → çok-adımlı/önkoşul soruları.
- **Multimodal** → şekil/tablo soruları (Faz 5, sonra).
- **Adaptive router** (kural tabanlı) → soruya göre kaç tur retrieval.
- **Agentic** → yalnız kanıt yetersizse, **en fazla 2-3 tur**, sadece iç kaynak.

## 1. Kısıt uzlaştırması (literatür ideali → BİZİM seçimimiz → neden)
Senin kısıtın: **DeepSeek flash, fine-tune YOK, tek geliştirici, Windows, mütevazı donanım, maliyet bilinçli.** Literatürün ağır yığını (Qwen3-4B/8B, ColPali, OpenSearch+Neo4j+Postgres, GPT-5.6) buna göre sadeleştirildi ama **mimari ve titizlik korundu**:

| Katman           | Literatür ideali             | **Bizim seçim (v1)**                                             | Neden                                                       |
| ---------------- | ---------------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------- |
| Üretici LLM      | GPT-5.6 / frontier           | **DeepSeek v4-flash** (zor soru-üretiminde v4-pro)               | Senin kararın; maliyet. Sağlayıcı değiştirilebilir kalır.   |
| Embedding        | Qwen3-Embedding-4B           | **BGE-M3** (dense+sparse+multivector, TR dahil, FT'siz)          | Tek modelde hibrit; eğitim yok; literatür de baseline diyor |
| Lexical          | OpenSearch BM25              | **rank_bm25** (saf Python) + TR normalizasyon                    | Java/servis yok; tek geliştirici                            |
| Reranker         | Qwen3-Reranker-4B            | **BGE-reranker-v2-m3** (FT'siz)                                  | Yerel, token maliyeti yok, güçlü                            |
| Vektör store     | Qdrant/Milvus küme           | **Qdrant yerel** (dosya/embedded)                                | Kurulum hafif; podman'da da koşar                           |
| Görsel retrieval | ColPali/ColQwen              | **v1: yok** → metin retrieval + **DeepSeek-vision** (crop besle) | ColPali TR'de kanıtsız+ağır; DeepSeek vision var            |
| Özet             | RAPTOR                       | **RAPTOR** (küme özetleri DeepSeek-flash ile)                    | Uzun kitap için literatür-önerisi                           |
| Graph            | Neo4j                        | **kazanimlar.json → SQLite/JSON kenarlar**                       | Deterministik omurga yeter; Neo4j sadece kanıtlanırsa       |
| Doğrulayıcı      | Farklı model ailesi          | **Kurallar + DeepSeek-pro** (ayrı rol) + uzman örneklemi         | DeepSeek içinde zayıf ayrışma; kurallarla güçlendir         |
| Fine-tuning      | Faz 4-7'de reranker/embed FT | **HİÇ YOK** — hep zero-shot/hazır                                | Senin kararın; FT yerine güçlü rerank+router+doğrulama      |

**Sapmaların bedeli (açık):** görsel retrieval ve model-ailesi çeşitliliği v1'de zayıf. Bunlar [[benchmark]] ablation'ında ölçülüp gerekirse Faz 5+'ta güçlendirilir. "Daha havalı diye" bileşen eklenmez — sadece ölçülen kazanç üretime girer.

## 2. Boru hattı (uçtan uca)
```
Kaynak derleyici (PDF→layout→öğe+koordinat+metadata; cevap-anahtarı & soru-sayfası İZOLE)
   → çok-temsilli chunk (atomik önerme / çocuk 150-300 tok / üst 700-1500 / tablo / görsel / ünite / kitap-ağacı)
   → indeks (BM25 + BGE-M3 dense + BGE-M3 sparse ; Qdrant + rank_bm25) + ZORUNLU metadata filtresi
   → görev yönlendirici (kural: kesin-bilgi / şekil-tablo / çok-adımlı / özet / cevaplanamaz)
   → paralel aday (BM25 top40 + dense top40 + sparse top30) → RRF
   → reranker (BGE-v2-m3) → ilk 8-12 kanıt + çeşitlilik + parent/figure genişletme
   → kanıt yeterliliği (skor marjı + kanal uzlaşması; yetersizse ≤2-3 tur ya da ÇEKİMSER)
   → göreve özel üretici (DeepSeek-flash) → iddia+atıf denetimi (sayfa/bbox) → cevap/soru/özet
```
**Değişmez kurallar:**
1. **Metadata filtresi zorunlu:** `müfredat_sürümü → sınıf → ders → ünite → kazanım → yetkili kaynak türü`. 12-bio sorusu 8-fen'e düşemez; lise sorgusu ortaokula sızamaz.
2. **Cevap sızıntısı yasağı:** ünite-sonu soruları, cevap anahtarı, soru sayfaları, özetteki hazır cevaplar **retrieval indeksinden ÇIKARILIR**. Yoksa ölçülen akıl yürütme değil, sızıntıdır.
3. **Atıf zorunlu:** her iddia sayfa/bbox'a bağlanır; desteklenmeyen iddia silinir ya da çekimser kalınır.
4. **Kapalı kaynak:** yalnız MEB kaynak havuzu; web yok. Kanıt yoksa "bu kaynaklarda yeterli kanıt yok" der.

## 3. Görev bazında akış (4 uygulama)
> Soru üretme + benzer soru için TAM tasarım ayrı dosyada: **[[soru-uretme]]** (kaynak: [[Literatür/Soru Üretme]]).
- **Kaynakla konuşma (QA):** filtre→hibrit→RRF→rerank→parent/figure→kaynak-sınırlı cevap→atıf→çekimser. Full-book long-context yalnız *baseline* olarak denenir, üretim değil.
- **Soru çözme:** 5 koşul ayrı ölçülür — closed-book / tüm-kitap long-context / text-RAG / multimodal / **oracle-evidence** (retriever kusursuz olsa). Bu ayrım "retrieval mi generator mı bozuk"u söyler. Çıktı: doğru şık + kanıt zinciri + her çeldiricinin neden yanlış olduğu + sayfa + kalibre güven + yetersiz-kanıt bayrağı. Sağlamlık: şık sırası/etiket karıştır, kök yeniden yaz, görsel/metin ayır, "kesinlikle/olamaz" ölç.
- **Soru üretme:** önce **kavram kartı** (doğrulanmış iddialar + mekanizma + önkoşul + yaygın yanılgılar + görsel + kazanım + kanıt). Sonra: blueprint hücresi seç → kanıt paketi → soru+cevap üret → **başka çağrı anahtarsız çözer** → critic (belirsizlik/çoklu-doğru/dil) → kanıt denetleyici → benzerlik/dedup → öğretmen onayı → (pilot sonrası) psikometri. Yayın şeması: `soru_id, sinif, ders, kazanimlar, bilissel_duzey, soru_metni, secenekler, dogru_cevap, cozum, celdirici_gerekceleri, kanitlar[{source,page,bbox}], gorsel_bagimliligi, zorluk_hedefi, uzman_onayi`.
- **Benzer soru üretme:** gerçek EBA sorusunu tohum al → kNN (kazanım+çözüm-izi+hata) ile örnek seç → varyant üret. **Varyant ≠ eşit güçlük** (ayrı kalibre); aynı aileden 2 soru aynı forma girmez.
- **Özet (187 sayfa):** **extract-then-abstract + RAPTOR**: atomik iddia→sayfa/görsel bağla→alt-başlık→ünite→kitap özeti; kazanım-kapsam matrisi; her cümle kaynak-destekli; %5/%10/%20 uzunluklar.

## 4. Türkçe işleme (zorunlu)
Unicode NFC; `I/ı` `İ/i` doğru dönüşüm; hece bölünmesi temizliği; bilimsel simge/alt-indis korunur; hem ham hem normalize alan indekslenir; sürümlü eşanlam (DNA↔deoksiribonükleik asit); **BM25 alanlarından en az biri KÖKLENMEZ** (aşırı kök biyolojik terimi bozar).

## 5. v1'de YAPMADIKLARIMIZ (kapsam netliği)
Fine-tuning yok · Neo4j/OpenSearch/Postgres kümesi yok (yerel dosya + SQLite yeter) · ColPali görsel-retrieval yok (DeepSeek-vision ile telafi) · web araması yok · full-book long-context üretim değil (yalnız baseline). Bunların hepsi [[benchmark]] ablation'ında ölçülüp *kanıtla* eklenir.
