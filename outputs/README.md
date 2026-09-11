# outputs/ — Kadir'in inceleme klasörü

Bu klasör ajanın ürettiği **özet, deney çıktısı ve soru/cevap kayıtlarını** tutar.
Kalıcı proje hafızası `docs/` altındadır (bkz. `docs/AGENTS.md` kural 2); buradaki
raporlar Kadir'in hızlı inceleyebilmesi için aynı içeriğin kopyasıdır.

| Yol | Ne |
|---|---|
| `00-PROJE-OZETI-2026-09-10.md` | 4 deponun bağımsız okumayla çıkarılmış özeti + bu makinenin gerçek durumu + belge çelişkileri |
| `EXP-009-model-karsilastirma/RAPOR.md` | Üretici LLM aday karşılaştırması (aynısı `docs/reports/EXP-009-uretici-llm-karsilastirma.md`) |
| `EXP-009-model-karsilastirma/run-*/karsilastirma-tablosu.md` | Model × ölçüt tablosu |
| `EXP-009-model-karsilastirma/run-*/soru-cevap-defteri.md` | **Her modelin her item'daki HAM cevabı** — insan incelemesi burada yapılır |
| `EXP-009-model-karsilastirma/run-*/raw/*.jsonl` | Çağrı başına ham kayıt (prompt kimliği, cevap, token, gecikme, hata) |
| `EXP-009-model-karsilastirma/run-*/suite.json` | Kullanılan item kümesi (deterministik, tekrar-üretilebilir) |
| `EXP-009-model-karsilastirma/run-*/summary-rescored.json` | Skorların makine-okur hâli |
| `EXP-009-model-karsilastirma/run-*/{provider_bench,rescore,qa_dump}.py` | Koşum + skorlama betikleri (tekrar-üretilebilirlik) |
| `EXP-009-model-karsilastirma/run-*/moonshotai_kimi-k3-OLCULEMEDI-kota/` | Başarısız koşumun kaydı (kural: başarısız denemeler silinmez) |

**Tüm deney durumları `İNSAN İNCELEMESİ BEKLİYOR`** — ortak kural 9 gereği ajan kendi
çıktısını "başarılı" işaretleyemez.

## EXP-011 — Sayfa hizalı chunk'lama ablation'ı (#53)
`EXP-011-chunk-ablation/RAPOR.md` — atıf sayfa-hassasiyetinin kök nedeni.
Sayfa aşan child chunk %63,4 → %0; `precision_page` teorik tavanı 0,723 → 1,000;
vekil retrieval'de recall düşmedi, top-1 sayfa hassasiyeti 0,647 → 0,970.
Bedel ölçüldü: top-5 bağlam hacmi −%16,6. **Kapı kararı #92'ye bağlı.**

## Korpus bütünlüğü — kitap ↔ kazanım müfredat uyuşmazlığı
`korpus-butunluk/RAPOR.md` — 10. sınıf biyoloji kitabında **"mitoz" 0 kez**
geçiyor ama `kazanimlar.json` ünite 1 olarak "Mitozu açıklar" diyor. Kitap yeni
(tema tabanlı) müfredattan, kazanım dosyası eskisinden. Kazanım kapsamı:
biyoloji %71, fizik %92, coğrafya/felsefe %100.

## Öğrenci senaryosu (backend uyumlu)
`ogrenci-senaryosu/` — backend kayıt biçiminde bir öğrenci (10-A, 19 ders,
3 kendi notu, 11 ders notu) ve uçtan uca koşum çıktısı: kasa izolasyonu 4/4
doğru, kendi dersinde 3 atıflı cevap.
