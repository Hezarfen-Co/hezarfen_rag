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
| RES-001 | ARAŞTIRMA (literatür+deney tasarımı) | Kaynakla konuşma, kanıtlı özetleme, Türkçe RAG model doğrulaması | Kadir incelemesi bekliyor (mimari/benchmark değişikliği ÖNERİR) |

> Not: EXP-001 bir **ölçüm/analiz**tir, model deneyi değil (LLM çalıştırılmadı).
> İlk **model deneyi** Faz 1 (text-RAG baseline) ile EXP-002 olacak.
