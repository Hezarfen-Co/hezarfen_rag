# reports/ — Deney & Araştırma Raporları

Ayrıntılı deney kayıtları ve literatür/teknik araştırma raporları burada.
Sohbette kalan araştırma **buraya** yazılır (kalıcı hafıza).

## Adlandırma
- Deney: `EXP-XXX-<kısa-slug>.md` (ör. `EXP-002-text-rag-baseline.md`)
- Araştırma: `RES-XXX-<slug>.md` veya `Literatür/` altındaki kaynak notları.

## Bir deney raporu neler içerir
Amaç · değiştirilen unsur · ayarlar (model/prompt/veri sürümü, commit, ortam) ·
başlangıç↔yeni karşılaştırma (aynı koşul) · otomatik metrikler · LLM-hakem (ayrı) ·
insan inceleme tablosu · başarılı/başarısız/sınırda/rastgele örnekler · ham çıktı+log
yolları · gecikme/token/donanım/maliyet · nihai durum (`İNSAN İNCELEMESİ BEKLİYOR`).

## Kayıtlar
| ID | Tür | Başlık | Durum |
|---|---|---|---|
| EXP-001 | ANALİZ (model-dışı) | Korpus görsel/tablo/diyagram yoğunluk analizi | İNSAN İNCELEMESİ BEKLİYOR |
| EXP-002 | DENEY | Çok-dersli kasa izolasyonu (4 kitap, ders+sınıf) | İNSAN İNCELEMESİ BEKLİYOR |
| EXP-003 | DENEY | Faz 0.8 OCR fallback + özet-PDF uçtan uca | İNSAN İNCELEMESİ BEKLİYOR |
| EXP-004 | DENEY | Faz 5 multimodal VLM captioning | İNSAN İNCELEMESİ BEKLİYOR |
| EXP-005 | DENEY | Non-bio kalite (kimya/fizik) + ayırt edici metrik | İNSAN İNCELEMESİ BEKLİYOR |
| EXP-006 | DENEY | Çok-ders özet + multimodal özet | İNSAN İNCELEMESİ BEKLİYOR |
| EXP-007 | DENETİM | Tam yazılım+AI denetimi + adversarial fuzz (17 fix) | İNSAN İNCELEMESİ BEKLİYOR |
| EXP-008 | DENEY | Measure-after-change re-baseline (kimya) | İNSAN İNCELEMESİ BEKLİYOR |
| EXP-009 | DENEY | Üretici LLM aday karşılaştırması (NVIDIA NIM ücretsiz uçlar) | İNSAN İNCELEMESİ BEKLİYOR |
| EXP-010 | DENETİM | Ürün-hazırlık denetimi (güvenlik·grounding·değerlendirme·operasyon; 62 bulgu) + MVP issue taslakları | İNSAN İNCELEMESİ BEKLİYOR |
| EXP-011 | ABLATION | Sayfa hizalı chunk'lama (#53): sayfa aşan child %63,4→%0, `precision_page` tavanı 0,723→1,000, vekil recall düşmedi, bağlam hacmi −%16,6 | İNSAN İNCELEMESİ BEKLİYOR |
| RES-001 | ARAŞTIRMA (literatür+deney tasarımı) | Kaynakla konuşma, kanıtlı özetleme, Türkçe RAG model doğrulaması | Kadir incelemesi bekliyor (mimari/benchmark değişikliği ÖNERİR) |
| RES-002 | ARAŞTIRMA | RagArt çözümlemesi (ders alınacak desenler + açıklar) | İNSAN İNCELEMESİ BEKLİYOR |
| RES-003 | ARAŞTIRMA (KUZEY YILDIZI) | Ürün-seviyesi RAG referans mimarisi + öncelik sırası | Kadir kaynaklı (2026-09-05) |

> Not: EXP-001 bir **ölçüm/analiz**tir, model deneyi değil (LLM çalıştırılmadı).
> EXP-009'un ham verisi + insan-okur soru/cevap defteri repo kökündeki
> `outputs/EXP-009-model-karsilastirma/` altındadır (Kadir'in inceleme yeri);
> bu klasördeki `EXP-009-uretici-llm-karsilastirma.md` aynı raporun kalıcı-hafıza kopyasıdır.
