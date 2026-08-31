# 🎯 Hezarfen RAG — Benchmark & Değerlendirme (KATI, kalite esaslı)

> Kaynak: [[Literatür/Hezarfen]]. Mimari: [[mimari]]. Adımlar: [[plan]].
> Kural: **ortalama skor değil**, her kritik alt-görevde **%95 güven aralığının
> ALT sınırı** kapıyı geçmeli. Kalite kaydı → [[deney-sonuclari]], maliyet → [[Maliyet]].
> Son güncelleme: 2026-08-29

## 1. Golden set nasıl kurulur (sızıntısız)
- **Bölme kaynak/ünite ailesiyle** yapılır — rastgele soru satırıyla DEĞİL. Aynı kitabın benzer sayfaları train ve test'e bölünmez.
- Varyantlar (görsel/kelime değişmiş) pHash + MinHash + embedding ile **tek gruba** alınır.
- **Cevap anahtarı ayrı, erişim-kontrollü** tutulur; soru-çözme indeksinde soru sayfaları BULUNMAZ.
- Her örnek kaydı: `soru · sınıf/ders/sürüm · görev türü · gold cevap + kabul varyantları · zorunlu kanıt span(lar)ı · sayfa/bbox · yasaklı kaynaklar · görsel bağımlılığı · hop sayısı · cevaplanabilirlik · kazanım · zorluk · uzman uyuşması`.
- Cevap anahtarları **iki uzmanca** doğrulanır; yayınevi anahtarı otomatik "mutlak doğru" sayılmaz.

## 2. Sorgu dağılımı (her ders için gizli test)
%25 kesin bilgi · %20 paraphrase · %15 multi-hop · %15 şekil/tablo · %10 global/özet · %10 cevaplanamaz · %5 çelişki/yazım-hatası/adversarial.
İlk hedef hacim: **12-bio 1200 sorgu · 8-fen 500 · 8-mat 500**; her yeni derste üretime çıkmadan **≥300 gizli sorgu**; her derste **≥50-75 layout-annotated sayfa**.

## 3. Release kapıları (KATI — %95 CI alt sınırı geçmeli)
| Katman | Metrik | Kapı |
|---|---|---|
| Native metin | CER | ≤ %0.5 |
| OCR sayfa | CER | ≤ %2 |
| Okuma sırası | Order F1 | ≥ 0.98 |
| Tablo | TEDS / cell F1 | ≥ 0.95 |
| Şekil–caption | Link F1 | ≥ 0.98 |
| ANN indeks | exact'e karşı recall | ≥ 0.995 |
| Retrieval | gold evidence Recall@20 | ≥ 0.98 |
| Retrieval | Recall@5 | ≥ 0.93 |
| Retrieval | nDCG@10 | ≥ 0.90 |
| Multi-hop | tüm gerekli kanıt Recall@20 | ≥ 0.95 |
| Görsel retrieval | gold page Recall@10 | ≥ 0.95 |
| Reranker | hybrid'e karşı nDCG | %95 CI ile pozitif |
| Kitap QA | uzman doğruluğu | ≥ 0.95 |
| Zor görsel/multi-hop | uzman doğruluğu | ≥ 0.90 |
| Grounding | claim-level faithfulness | ≥ 0.99 |
| Grounding | desteksiz iddia oranı | ≤ %0.5 |
| Atıf | citation precision / recall | ≥ 0.99 / ≥ 0.97 |
| No-answer | yanlış cevap verme | ≤ %2 |
| Kalibrasyon | ECE | ≤ 0.05 |
| Özet | temel kazanım kapsamı | ≥ 0.95 |
| Özet | kaynak-destekli iddia | ≥ 0.99 |
| Özet | çelişki | 0 |
| Soru üretme (yayın) | doğru anahtar + kaynak desteği | %100 |
| Soru üretme | belirsiz/çoklu-doğru | ≤ %1 |
| Soru üretme | ilk öğretmen kabulü | ≥ %85 |
| Güvenlik | yasaklı cevap-anahtarı retrieval | 0 olay |

> Bunlar literatürün önerdiği **ürün kapıları** (evrensel standart değil). Kalite önceliğin bunları gerektiriyor. Eşik geçilene kadar optimize; [[deney-sonuclari]]'na kaydet.

## 4. Değerlendirme araçları
- **Dev hızı için:** DeepEval / RAGAS (faithfulness, contextual precision/recall, answer relevancy, hallucination) — **tek kapı değil**.
- **Claim-level teşhis:** RAGChecker (retriever claim-recall, context precision, faithfulness, gürültü hassasiyeti, hallucination, context utilization) → "retrieval mi generator mı bozuk" ayrımı.
- **Özet:** ROUGE/BERTScore TEK BAŞINA değil → uzman temel-iddia coverage + FActScore-tarzı atomik olgu desteği + faithfulness + completeness + conciseness + atıf + şekil/tablo coverage + "özetten cevaplanan kaynak-soru oranı".
- **Soru çözme ablation'ı:** closed-book / long-context / text-RAG / multimodal / **oracle** koşulları ayrı raporlanır.
- **Judge kalibrasyonu:** otomatik judge ≥~150 insan etiketiyle kalibre (ARES yaklaşımı); güven aralığı üret.
- **Soru üretme psikometrisi (pilot sonrası):** madde güçlüğü p · point-biserial ≥0.25 (tercihen 0.30+) · çeldirici seçilme · çalışmayan çeldirici · IRT 2PL/3PL · DIF (sınıf/cinsiyet/okul) · süre · kazanım coverage. Klasik analiz ~200 yanıt, kararlı IRT/DIF 500+.

## 5. Zorunlu ablation (her bileşen kanıtla girer)
BM25 → +dense (RRF) → +reranker → +proposition/parent chunk → +visual index → +curriculum graph → +RAPTOR → +bounded agent.
Her bileşen için: kalite · p50/p95 latency · **maliyet (→[[Maliyet]])** · token · retrieval hatası · generator hatası · sınıf/ders regresyonu. **"Havalı" diye tutulmaz; yalnız istatistiksel+pratik kazanç üretime alınır.**

## 6. Kapsam sırası (release kalitesi nerede kanıtlanır)
1. **Vertical slice: 12-bio** (tam kitap + özet + defter + görsel soru + 29 kazanım).
2. **İkinci dalga: 8-fen + 8-mat** (+ mümkünse 8-türkçe/sosyal) → bilimsel metin + şekil + matematik işlem + dil birlikte sınanır.
3. Sistem baştan **tüm sınıfları destekleyen metadata** ile kurulur; ama release kalitesi **8. ve 12.**'de kanıtlanır. Diğer sınıflar aynı boru hattından geçer.

## 7. Veri boşlukları (benchmark'ı etkileyen — [[plan]] Faz 0/3'te kapatılır)
- `sorular.json` = **cevap+varlık manifesti**, tam soru DEĞİL: soru gövdeleri/şıkları yok, birçok görsel eksik, `kazanimlar` boş. → soru-çözme için gövde/görsel toplanmalı + soru–kazanım eşlemesi yapılmalı.
- Konu özeti PDFّlerinde sütun sırası karışabiliyor → layout parser.
- Ortaokul (5-8) EBA'da özet/soru YOK → ortaokul yalnız kitap; benchmark 8. sınıfta **kitap + (varsa) soru** ile kurulur, lise dört-kaynakla zengin.
