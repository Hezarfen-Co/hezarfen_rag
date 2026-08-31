# Proje 1

# Otomatik soru üretme
En iyi yaklaşım “PDF’yi LLM’ye ver, on soru iste” değil. Güçlü üretim hattı:

Sınav blueprint’i ve kazanım dağılımı
Kaynak metne dayalı RAG
Bloom seviyesi ve hedeflenen bilişsel işlem
Ayrı soru üretici, çözücü ve eleştirici modeller
Cevabın bağımsız olarak yeniden çözülmesi
Benzer/sızmış soru kontrolü
Öğretmen onayı
Öğrenci cevaplarından IRT zorluk ve ayırt edicilik kalibrasyonu
DIF ile gruplar arası yanlılık kontrolü

Distraktörlerde gerçek öğrenci hataları çok değerli. NAACL 2024 çalışmasında, benzer gerçek
sorulardan kNN ile örnek seçmek diğer prompt yöntemlerinden daha iyi çalıştı; LLM’lerin
matematiksel olarak makul yanlış cevaplar üretebildiği fakat gerçek öğrencilerin yaygın kavram
yanılgılarını çoğu zaman bilemediği bulundu. Bu nedenle bir “Türk öğrenci hata ve kavram
yanılgısı bankası” ciddi bir rekabet avantajı olabilir. 


# Literatür 
Dostum, ana sonuç şu: savunulabilir ürün “PDF → 100 soru” değil; **çok kipli belge anlayışı + sınav kapsam planı + kanıta bağlı madde üretimi + otomatik ret kapıları + uzman incelemesi + psikometrik öğrenme** sistemidir.

26 Ağustos 2026’ya kadar yayımlanmış hakemli derlemeleri, deneysel çalışmaları, belge-anlama makalelerini ve ürünlerin resmî teknik materyallerini taradım. Bu, PRISMA protokollü tam bir sistematik derleme değil; kalite ve güncellik öncelikli kapsamlı bir teknik taramadır.

## 1. Literatürün söylediği en önemli şeyler

|Çalışma|Tasarım ve bulgu|Ürüne etkisi / sınırlaması|
|---|---|---|
|PLOS ONE 2026 sistematik derleme ve ağ meta-analizi|15 sağlık eğitimi çalışması ve 5 LLM incelendi. GPT-4 sorularının uzman puanları bakımından insan sorularına yakın olabileceği bulundu; fakat kanıt kesinliği çoğu karşılaştırmada **çok düşük**. Çalışmaların yalnızca 8’i soruları öğrencilere uyguladı.|Akıcılık ve uzman beğenisi yeterli kanıt değildir. Öğrenci cevaplarıyla pilot zorunlu olmalı.|
|Medical Teacher 2026 meta-analizi|12 çalışma, ikisi randomize. Güçlükte SMD 0,05; ayırt edicilikte SMD −0,10 ile genel fark bulunmadı. Ancak heterojenlik sırasıyla %82 ve %70; eşitlik/yanlılık çok az araştırılmış.|“Ortalama olarak fark yok” sonucu ürün veya alanlar arasında eşdeğerlik anlamına gelmiyor. Dil, alan ve sınav türüne özel doğrulama gerekli.|
|[Maity ve arkadaşları, Computers & Education: AI 2025](https://doi.org/10.1016/j.caeai.2025.100370)|3.502 okul kitabı bağlamı, beş LLM, sıfır ve sekiz örnekli prompting. Sekiz örnek; kapsam, kullanılabilirlik, ilgi ve Bloom uyumunu geliştirdi. GPT‑4 Turbo’nun sekiz örnekli kapsam puanı 4,90 iken cevaplanabilirlik 3,88; insan tabanı 4,89 ve 4,68.|Kaliteli ve çeşitlendirilmiş örnekler gerçekten faydalı. Ancak sonuç insan derecelendirmesi; psikometrik kaliteyi göstermiyor. Makaledeki bazı örnek soruların verilen kısa bağlamı aşması da “yalnız kaynaktan üretim” kapısının gereğini gösteriyor.|
|[Ahmed ve arkadaşları, BMC Medical Education 2025](https://link.springer.com/article/10.1186/s12909-025-06881-w)|GPT‑4’ün ürettiği 220 sorudan yalnızca 49’u değişikliksiz kabul edildi; 103’ü düzeltildi, 68’i reddedildi. 142 öğrencilik uygulamada ortalama güçlük ve ayırt edicilikte anlamlı fark yoktu. Buna rağmen DI > 0,30 olan soru sayısı AI’da 12/50, insanda 24/50 idi.|“Kabul veya düzeltilebilir” oranını tek KPI yapmak yanıltıcıdır. Değişikliksiz kabul, düzeltme süresi ve yüksek ayırt edicilik ayrı izlenmeli.|
|[Law ve arkadaşları, yüksek riskli sınav kohortu 2025](https://link.springer.com/article/10.1186/s12909-025-06796-6?utm_source=chatgpt.com)|24 aday, 100 AI ve 100 insan sorusu. AI soruları daha kolaydı; ayırt edicilik benzerdi. Daha fazla uygunsuz güçlük, ilgisizlik ve düşük düzey bilişsel işlem görüldü; üretim süresi 24,5’e karşı 96 kişi-saat oldu.|Verimlilik güçlü; yüksek bilişsel düzey ve içerik doğruluğu hâlâ insan kapısına ihtiyaç duyuyor. Örneklem küçük.|
|[Anschuetz ve arkadaşları, gerçek yüksek riskli uzmanlık sınavı 2026](https://link.springer.com/article/10.1186/s12909-026-10082-4?utm_source=chatgpt.com)|304 aday. 90 AI destekli soru geliştirildi; madde analizine 12 AI, 14 yeni uzman ve 89 eski banka sorusu girdi. AI soruları daha kolaydı: doğru cevap oranı %84,7; uzman sorularında %73,5, banka sorularında %69,4. Ayırt edicilik benzer, işleyen çeldirici sayısı daha zayıftı.|Çok aşamalı inceleme sonrasında bile güçlük ve çeldirici sorunu kalıyor. Güncel ve gerçek sınav ortamındaki en önemli kanıtlardan biri.|
|[Al‑Najafi ve arkadaşları, randomize çalışma 2026](https://pubmed.ncbi.nlm.nih.gov/42304363/?utm_source=chatgpt.com)|258 öğrenci, 112 maddelik açık kaynaklı biçimlendirici sınav. ChatGPT üretim, Gemini doğrulama hattı 5,6 kat zaman kazandırdı. Kabul edilebilirlik ve çeldirici verimliliği benzerdi; öğrenci yazımı sorular biraz daha ayırt ediciydi.|Ayrı üretici/doğrulayıcı model yararlı olabilir; fakat sonuç açık kaynaklı, düşük riskli sınava ait.|
|[Westacott ve arkadaşları, eş biçimli AIG varyantları 2023](https://link.springer.com/article/10.1186/s12909-023-04457-0?utm_source=chatgpt.com)|2.218 öğrenci, aynı 50 modelden oluşturulan dört sınav. 46 madde ailesinin 21’inde varyantlar arasında en az 0,15 güçlük farkı görüldü.|Aynı şablondan çıkan sorular eş güçlükte sayılamaz. Her varyant ayrı kalibre edilmeli; aile kimliği saklanmalı.|

Ayrıca temel tasarım literatürü şu ortak resmi veriyor:

- [Kurdi ve arkadaşlarının 93 çalışmalık sistematik derlemesi](https://link.springer.com/article/10.1007/s40593-019-00186-y?utm_source=chatgpt.com), kontrollü güçlük, sunum, geri bildirim ve karşılaştırılabilir değerlendirme metriklerinin uzun süredir zayıf alanlar olduğunu gösteriyor.
- Klasik AIG yaklaşımı, uzman tarafından oluşturulan **bilişsel model → madde modeli → kontrollü kombinasyon** zinciridir. Gierl ve arkadaşları tek modelden 1.248 soru üretmiş, fakat operasyonel kullanımdan önce ampirik doğrulama gerektiğini açıkça belirtmiştir. [Gierl et al., 2012](https://doi.org/10.1111/j.1365-2923.2012.04289.x)
- [EMNLP 2024 çeldirici üretimi derlemesi](https://aclanthology.org/2024.emnlp-main.799/?utm_source=chatgpt.com), retrieval, ontoloji, sinirsel üretim ve LLM yöntemlerini inceliyor; BLEU, benzerlik veya otomatik sıralama puanlarının anlamsızlık, çoklu doğru ve gerçek çeldirici işlevini ölçemediğini vurguluyor.
- [ACL 2026 MAFIG](https://aclanthology.org/2026.acl-long.1267/?utm_source=chatgpt.com) çalışması, güçlüğü doğrudan “kolay/orta/zor yaz” komutuyla değil; bilişsel ve dilsel özellik kısıtlarını ayrı değerlendiricilerle iteratif olarak kontrol ederek daha iyi yönlendiriyor. Yine de gerçek güçlük öğrenci verisiyle belirlenmeli. Nitekim güncel bir [2026 ön çalışmasında](https://arxiv.org/abs/2607.28634v1?utm_source=chatgpt.com) en iyi LLM güçlük tahmini QWK 0,578’de kalmış ve zor sorularda başarısız olmuştur.

## 2. Önerdiğim ürün mimarisi

```
flowchart TD
    A["PDF + kazanımlar"] --> B["Hibrit belge ayrıştırma"]
    B --> C["Sürümlü kanıt grafiği"]
    C --> D["Önem analizi + sınav planı"]
    D --> E["Aday madde fabrikası"]
    E --> F{"Kalite kapıları"}
    F -->|Reddet veya düzelt| E
    F -->|Geçir| G["Uzman incelemesi"]
    G --> H["Düşük riskli pilot"]
    H --> I["CTT, IRT, DIF ve madde bankası"]
    I --> D
```

Bu tasarım [Evidence-Centered Design](https://onlinelibrary.wiley.com/doi/pdf/10.1002/j.2333-8504.2003.tb01908.x?utm_source=chatgpt.com) mantığına oturmalı:

- **Öğrenci modeli:** Hangi bilgi, beceri ve muhakemeyi ölçmek istiyoruz?
- **Kanıt modeli:** Doğru veya yanlış cevap bu beceri hakkında ne kanıt sunacak?
- **Görev modeli:** Bu kanıtı ortaya çıkaracak soru/stimulus nasıl olmalı?
- **Birleştirme modeli:** İçerik, bilişsel düzey, görsel kullanım ve psikometrik hedefler sınav formunda nasıl dengelenecek?

Bloom etiketi tek başına kanıt modeli değildir. “Analiz” yazılmış bir soru, öğrenciden gerçekten karşılaştırma, ilişki kurma veya çok adımlı çıkarım istemiyorsa analiz sorusu değildir.

## 3. PDF’yi gerçekten anlamak

“Tam anlama”yı pazarlama cümlesi olarak değil, sınanabilir bir sözleşme olarak tanımlamak gerekir:

1. Kullanılan her iddia sayfa ve koordinata bağlanabiliyor.
2. Tablo, grafik, şekil veya formül yapılandırılmış biçimde yeniden kurulabiliyor.
3. Cevap, bu yapı üzerinde bağımsız olarak yeniden hesaplanabiliyor.
4. Metin–şekil–tablo çapraz referansları korunuyor.
5. Sistem anlayamadığı veya düşük güvenli içeriği soru üretmeden reddedebiliyor.

[Docling](https://arxiv.org/pdf/2408.09869?utm_source=chatgpt.com), programatik PDF metnini koordinatlarıyla çıkartıp sayfayı ayrıca render eden; ardından layout, tablo, OCR ve okuma sırası işleyen iyi bir açık kaynak başlangıç mimarisidir. [OmniDocBench](https://arxiv.org/html/2412.07626?utm_source=chatgpt.com) ise metin, tablo, formül ve okuma sırasını ayrı değerlendirmemiz gerektiğini gösteriyor. Güncel [PaddleOCR‑VL‑1.5](https://arxiv.org/html/2601.21957?utm_source=chatgpt.com) ön çalışması OCR, tablo, formül, grafik, text spotting ve okuma sırasını kapsayan 0,9B bir model sunuyor ve kendi testinde OmniDocBench v1.5 üzerinde %94,5 bildiriyor; ancak bu üretici kaynaklı/preprint sonuç mutlaka Türkçe ders kitabı veri kümesinde yeniden sınanmalı.

|PDF öğesi|Önerilen teknik|Saklanacak kanonik temsil|Temel test|
|---|---|---|---|
|Dijital metin|PDF nesne katmanından metin + font + koordinat; OCR yalnız gerektiğinde|Paragraf, başlık, liste, sayfa, bounding box, okuma sırası, güven|CER/WER; sayı, birim ve özel karakter doğruluğu; okuma sırası|
|Taranmış sayfa|Sayfa sınıflandırma, deskew/dewarp, OCR, layout segmentation|Aynı metin şeması + OCR güveni|Türkçe CER; `ı/i/İ/I`, diakritik, sayı ve birim hataları|
|Tablo|Tablo algılama, satır–sütun ve hücre span rekonstrüksiyonu, başlık yolu ve dipnot bağlantısı|Hücre grafiği veya HTML; her hücre için sayfa/koordinat|TEDS, GriTS, hücre değeri exact match, başlık–hücre ilişki F1. PubTables‑1M/GriTS|
|Grafik|Başlık, eksen, ölçek, birim, legend ve seri ayrıştırma; grafiği veri tablosuna dönüştürme|Seri–x–y tablosu + ölçek ve legend|RMS-F1, sayıların bağıl hatası, eksen/legend F1, grafik QA doğruluğu. [DePlot](https://aclanthology.org/2023.findings-acl.660/)|
|Bilimsel şema / akış|OCR + nesne/etiket algılama + ok/çizgi ilişkilendirme + VLM|`düğüm–ilişki–düğüm` grafiği; her ilişkinin görsel bölgesi|Düğüm/kenar precision–recall, ok yönü doğruluğu, caption eşleştirme|
|Fotoğraf / tıbbi görüntü|Önce görsel türü ve yeterlilik sınıflandırması; ardından alan modeli ve bölgesel grounding|Nesneler, bölgeler, özellikler ve güven|Uzman doğruluğu, bölge IoU, kalibrasyon; düşük güven durumunda soru üretmeme|
|Denklem|Formül OCR → LaTeX/MathML → ifade ağacı; sembol tanımlarıyla bağlantı|Denklem AST’si, sembol tablosu, varsayımlar|CDM, normalize ifade eşleşmesi, sembolik/nümerik eşdeğerlik. [Nougat](https://proceedings.iclr.cc/paper_files/paper/2024/file/a39a9aceda771cded859ae7560530e09-Paper-Conference.pdf?utm_source=chatgpt.com), [CDM](https://arxiv.org/abs/2409.03643?utm_source=chatgpt.com)|
|Kod|Girintiyi koruyan OCR, dil algılama, parser/linter; güvenli sandbox’ta test|Kaynak kod + AST + çıktı/test ilişkileri|Parse oranı, test başarısı, karakter exact match|
|Harita, zaman çizgisi|Legend, bölge, etiket, tarih ve konumsal/zamansal ilişki çıkarma|Bölge/olay grafiği|Etiket, tarih, ilişki F1; legend kapsamı|
|Dipnot ve çapraz referans|“Şekil 3”, yıldız, üst simge ve sayfa geçişlerini ilişkilendirme|Belge grafiğinde referans kenarları|Bağlantı precision/recall|

Önemli prensip: **Genel bir VLM tek başına PDF ayrıştırıcısı olmamalı.** Doğrudan metin katmanı, uzman tablo/formül modelleri ve VLM birbirlerini tamamlamalı. VLM özellikle semantik şekil yorumu ve belirsiz durumlarda yükseltme katmanı olmalı.

Grafik ve tablolarda LLM’ye aritmetik yaptırmak yerine veri tablosunu SQL/Decimal koduyla; formülleri ise sembolik matematik motoruyla hesaplatmak daha güvenlidir.

### Görselden soru üretmek için ek kapılar

- Görsel ve yapılandırılmış temsil, birbirinden bağımsız iki çözücü tarafından aynı cevaba ulaştırmalı.
- Görsel kaldırıldığında soru hâlâ cevaplanabiliyorsa “görsel gereklilik” düşüktür; soru gerçekte şekil okuma becerisini ölçmüyordur.
- Caption cevabı açıkça veriyorsa cevap sızıntısı işaretlenmeli.
- Okunamayan eksen, belirsiz renk, sıkışmış legend veya düşük çözünürlük varsa kesin sayı sorusu üretilmemeli.
- Türetilmiş bir cevapta sadece şekle değil, kullanılan eksen noktaları/hücreler ve hesap ifadesine de provenance tutulmalı.

## 4. “Önemli yer” analizi nasıl yapılmalı?

Önemli görünmek ile ölçmeye değer olmak aynı şey değil. Başlıkta geçen bir ayrıntı sınav hedefi olmayabilir; küçük bir tabloda yer alan ilişki temel kazanım olabilir.

Önerdiğim süreç:

1. Belgeden doğrudan soru değil, önce **atomik iddialar** çıkarılır: tanım, neden–sonuç, karşılaştırma, süreç adımı, kural, istisna, formül ve örnek.
2. Her iddia kazanımlarla eşleştirilir. İlk aşamada bir bi-encoder geniş aday kümesi bulur; cross-encoder/NLI modeli nihai eşleşmeyi ve ilişki türünü belirler.
3. İddialar şu özelliklerle sıralanır:
    - kazanım benzerliği ve zorunlu müfredat ağırlığı,
    - öğretmenin “temel/yardımcı/ayrıntı” etiketi,
    - başlık, hedef, özet, tanım kutusu, örnek ve görsel-caption gibi doküman sinyalleri,
    - kavram grafiği merkeziliği ve önkoşul ilişkileri,
    - geçmiş öğrenci hataları ve kavram yanılgıları,
    - mevcut soru bankasındaki kapsam açığı,
    - ölçülebilirlik ve tekil kanıt bulunabilirliği.
4. Ağırlıklar elle sabitlenmek yerine öğretmenlerin kabul/ret kararlarından **learning-to-rank** ile öğrenilir. Düşük güvenli eşleşmeler aktif öğrenme için uzmana gider.
5. Son seçim, sadece ilk N skoru almakla yapılmaz. Bir optimizasyon katmanı şu matrisi doldurur:
    
    `içerik/kazanım × bilişsel işlem × soru türü × modalite × hedef güçlük özelliği`
    
6. Aynı iddiayı veya aynı bilişsel işlemi farklı cümlelerle tekrarlayan maddeler embedding + cross-encoder + madde ailesi denetimiyle elenir.

[AIED 2019 çalışmasında](https://link.springer.com/chapter/10.1007/978-3-030-23204-7_6) LexRank dört veri kümesinde sağlam bir “question-worthy sentence” tabanı vermiştir. Ancak ürün seviyesinde bunu yalnızca bir özellik olarak kullanmak; kazanım, önkoşul, ölçülebilirlik ve kapsam açığıyla birleştirmek gerekir.

Kazanım verilmemişse sistem kazanımları önerebilir ama onları otomatik olarak resmî kabul etmemelidir. Öğretmen onayından sonra sınav planına girmeliler.

## 5. Üretim ve çeldirici tekniği

Her aday madde serbest metin değil, yapılandırılmış bir nesne olmalı:

```
item:
  evidence_claim_ids: [...]
  source_regions: [...]
  learning_outcome: ...
  cognitive_operation: compare | infer | calculate | diagnose
  modality: text | table | chart | diagram | mixed
  stem: ...
  key: ...
  distractors:
    - text: ...
      misconception_id: ...
      why_incorrect_evidence: [...]
  rationale: ...
  target_difficulty_features: [...]
  family_id: ...
  model_prompt_versions: ...
```

Üretim stratejisi:

- Her özellik hücresi için 3–10 aday oluştur; en iyisini üretmeye çalışmak yerine kötüleri erken reddet.
- Few-shot örnekleri alan, bilişsel işlem ve soru türüne göre retrieval ile seç.
- RAG yalnızca **yetkilendirilmiş kaynak havuzunda** çalışsın. Açık web bilgisi kaynak-temelli soruya sessizce karışmamalı.
- Bloom adından ziyade gözlenebilir işlem ver: “iki seriyi karşılaştır”, “iki kanıtı birleştir”, “kuralı yeni örneğe uygula”, “en tutarlı tanıyı seç”.
- Güçlük; cümleyi uzatarak değil, gereken çıkarım adımı, bilgi entegrasyonu, soyutlama, çeldirici yakınlığı ve ipucu miktarıyla yönetilmeli.

### Çeldirici için iki ayrı çalışma modu

**Katı kaynak modu:** Kök, anahtar, açıklama ve çeldiricilerin yanlışlığı yalnız PDF’den doğrulanır. Çeldiriciler:

- iki kavramın niteliğini değiştirme,
- neden–sonuç yönünü ters çevirme,
- komşu kategori veya terim,
- tablo satırı/sütunu karıştırma,
- yanlış birim, işaret veya işlem,
- süreç adımını yanlış sıraya koyma

gibi kontrollü dönüşümlerden oluşturulur.

**Kaynak + yanılgı bankası modu:** Anonim öğrenci yanlış cevapları, öğretmen etiketleri ve hata günlükleri kullanılır. Her çeldiricinin `misconception_id` ve veri kaynağı bulunur. Anahtar yine PDF’den cevaplanabilir olmalı. Bu modda dış kaynaklı çeldirici provenance’ı uzmana açıkça gösterilmelidir.

Her çeldirici için üç ayrı şart aranmalı:

1. Kaynağa göre doğru cevap değildir.
2. Aynı semantik türde ve dilbilgisel yapıdadır.
3. Gerçek veya makul bir yanlış muhakeme yolunu temsil eder.

## 6. Otomatik doğrulama kapıları

Ayrı modeller kullanmak faydalıdır fakat modellerin hataları korelasyonlu olabilir. Bu yüzden “üç model onayladı” doğruluk kanıtı sayılamaz.

Önerdiğim kapılar:

- **Deterministik madde kuralları:** şema, seçenek sayısı, tekrar, anahtar dağılımı, seçenek uzunluğu, dilbilgisel uyum, “hepsi/hiçbiri”, mutlak ifadeler, olumsuz kök, homojenlik. [NBME’nin 2024 kılavuzu](https://info.nbme.org/rs/552-QHC-046/images/NBME_Item-Writing-Guide.pdf?version=0&utm_source=chatgpt.com), önemli kavramı ölçme, uygulama düzeyi, cover-the-options ve homojen seçenekleri temel kurallar olarak veriyor.
- **Kanıta bağlılık:** kök, anahtar ve açıklamadaki her doğrulanabilir iddia için destekleyen sayfa/bölge bulunmalı. Çeldiricinin yanlışlığı da kanıta veya açık dönüşüm kuralına bağlanmalı.
- **Tek doğru denetimi:** kaynakla çalışan bağımsız çözücü, seçenekleri karıştırılmış biçimde her defasında aynı anahtara ulaşmalı. Model örneklemeleri arasında cevap entropisi yüksekse soru reddedilmeli.
- **Cevap sızıntısı:** doğru seçeneğin uzunluğu, kökteki kelimeleri tekrar etmesi, gramer uyumu, diğerlerinden farklı özgüllükte olması ve kapalı kitap çözücünün içerik bilmeden seçebilmesi incelenmeli.
- **Çok kipli denetim:** orijinal sayfa görüntüsü, crop ve çıkarılan tablo/grafik/formül aynı sonucu vermeli.
- **Kapsam ve tekrar:** aynı kazanım, iddia ve bilişsel işlemin gereğinden fazla kullanımı engellenmeli.
- **Yanlılık ön taraması:** kontrollü demografik değişimler, dil ve bölgesel ifadeler, gereksiz kimlik bilgileri. Nihai kanıt öğrenci verisindeki DIF analizidir.
- **Güvenlik:** PDF içindeki metin talimat değil, güvenilmeyen veri kabul edilmeli. Dosyaya gömülü dolaylı prompt injection mümkündür; dosya içerikleri araç yetkilerine ulaşmamalıdır. [OWASP prompt injection rehberi](https://genai.owasp.org/llmrisk2023-24/llm01-24-prompt-injection/?utm_source=chatgpt.com)

Ayrıca iki farklı doğruluk rozeti tutmak gerekir:

- **Kaynağa sadık:** PDF bu cevabı destekliyor.
- **Dünya bilgisiyle doğrulanmış:** PDF’deki bilgi güncel ve yetkili referanslarla uyumlu.

PDF eski veya hatalıysa sistem sessizce düzeltmemeli; çelişkiyi işaretlemeli ve soru üretmemeli.

## 7. Değerlendirme metrikleri

|Katman|Ölçülmesi gerekenler|
|---|---|
|Belge ayrıştırma|Layout sınıfı mAP; OCR CER/WER; sayı–birim exact match; okuma sırası normalize edit distance/Kendall τ; tablo TEDS/GriTS; grafik RMS-F1; formül CDM; caption ve çapraz referans precision/recall|
|Kanıt grafiği|İddia çıkarma precision/recall; sayfa/bounding-box doğruluğu; çapraz modal ilişki F1; güven kalibrasyonu için Brier/ECE|
|Önem/kazanım|Kazanım top-k recall, macro-F1, uzman nDCG; “must-know” kapsamı; hedef–gerçek sınav planı sapması; tekrar oranı; kapsam dışı madde oranı|
|Madde kalitesi|Anahtar doğruluğu; tek doğru oranı; cevaplanabilirlik; belirsizlik; kaynak iddiası coverage/precision; item-writing flaw oranı; bilişsel işlem uyumu|
|Uzman süreci|Değişikliksiz kabul, küçük düzeltme, büyük düzeltme, ret; madde başına inceleme süresi; ret nedeni; değerlendiriciler arası weighted κ, Gwet AC1 veya Krippendorff α|
|Çeldirici|Uzman inandırıcılığı; yanılgı izlenebilirliği; her seçeneğin seçilme oranı; seçenek point-biserial’i; işleyen çeldirici sayısı; çeldirici verimliliği|
|Klasik test kuramı|Facility `p`; düzeltilmiş point-biserial; üst–alt grup DI; cevap süresi; boş bırakma; form düzeyinde KR-20/omega ve SEM|
|IRT|2PL/3PL veya uygun Rasch modeliyle `a`, `b`, gerekirse `c`; item fit; item/test information; parametre standart hatası; yerel bağımlılık|
|Adalet|Mantel–Haenszel, lojistik regresyon veya IRT-LR DIF; etki büyüklüğü ve güven aralığı; dil, cinsiyet, bölge ve erişilebilirlik grupları|
|Operasyon|Kaynak/model/prompt sürümüne göre hata; soru ailesi maruziyeti; parametre drift’i; uzman düzeltmelerinin zaman içindeki azalması|

Bazı önemli ayrımlar:

- `p`, doğru cevap oranıdır; yüksek değer daha kolay madde demektir.
- Güvenilirlik form düzeyindedir; tek bir sorunun “KR-20’si” olmaz.
- “Bir çeldiriciyi öğrencilerin %5’inden azı seçtiyse işlevsizdir” sık kullanılan bir kuraldır ama evrensel eşik değildir. Örneklem, seçenek sayısı ve sınav amacı dikkate alınmalı.
- Ahmed çalışmasındaki DI > 0,20 biçimlendirici ve > 0,30 toplamlı sınav referansları yerel uygulama örneğidir; her ürün için evrensel kabul eşiği değildir.
- Sabit bir pilot örneklem sayısı vermek yerine, hedef IRT modeli, parametre belirsizliği, grup/DIF ihtiyaçları ve anchor tasarımıyla simülasyon yapılmalı.

### Psikometrik öğrenme döngüsü

Yeni soru için model yalnızca `a` ve `b` parametrelerine **önsel tahmin** verebilir. Sonrasında:

1. Onaylı soru düşük riskli sınavda puanlanmayan pretest maddesi olarak gömülür.
2. Eski kalibre anchor maddelerle birlikte uygulanır.
3. Bayesçi/hiyerarşik IRT ile parametreler cevap geldikçe güncellenir.
4. Aynı şablon ailesindeki sorulara ortak aile etkisi verilir; yerel bağımlılık incelenir.
5. Aynı aileden iki kardeş soru aynı sınav formuna konmaz.
6. Parametre belirsizliği yüksekse madde “kalibre” sayılmaz.

## 8. Mevcut ürünlerden öğrenilecekler

|Ürün|Kamuya açık yetenek|Alınacak ders / eksik|
|---|---|---|
|[Kahoot AI](https://support.kahoot.com/hc/en-us/articles/40803785990675-How-to-generate-a-kahoot-with-AI?utm_source=chatgpt.com)|Yaklaşık 154 sayfalık PDF, 70 dil, seviye ve soru sayısı ayarı, ABD standart kodları, öğretmen incelemesi. Kahoot da hatalı/yanlı sonuç olabileceğini açıkça söylüyor.|Hızlı tüketici akışı iyi; ancak kamuya açık belge düzeyinde kaynak bölgeleri, otomatik ret ve psikometrik öğrenme görünmüyor.|
|[QuestionWell](https://questionwell.org/?utm_source=chatgpt.com)|Standart, bilişsel düzey ve pedagojik lensler. Şirketin [2026 teknik çalışması](https://questionwell.org/hubfs/Papers/mcq-paper-llncs-main.pdf?hsLang=en&utm_source=chatgpt.com), 1.680 tercih çiftiyle SFT + DPO kullanıp beş yüzey kusurunda %96 kusursuz oran bildiriyor.|Rubrikle sentetik veri ve post-training iyi fikir. Fakat şirket yazarlı çalışma 50 İngilizce quiz, tek prompt ve otomatik yüzey ölçülerine dayanıyor; doğruluk, çeldirici işlevi ve psikometriyi kanıtlamıyor.|
|[MagicSchool](https://www.magicschool.ai/tools/multiple-choice-quiz-assessment?utm_source=chatgpt.com)|Verilen metinden, sınıf seviyesine uyarlanmış MCQ üretimi.|Öğretmen deneyimi sade; kamuya açık teknik/psikometrik doğrulama sınırlı.|
|[Meazure ADE](https://www.meazurelearning.com/exam-technology/ade-item-authoring-exam-development?utm_source=chatgpt.com) ve [Itematic](https://www.meazurelearning.com/exam-technology/itematic-automated-item-generation?utm_source=chatgpt.com)|Rol tabanlı yazım–inceleme–onay akışı, sürüm ve denetim izi, blueprint, performans istatistikleri. Itematic’te uzman bilişsel model, şablon ve değişkenleri tanımlıyor; sistem benzersiz alt kümeyi üretiyor.|Güvenilir madde geliştirme iş akışına en yakın ürün düşüncesi. LLM esnekliği eklenebilir ama uzman modeli, sürümleme ve psikometrik kapılar korunmalı.|

Kamuya açık kanıta göre bu ürünlerin hiçbiri tek başına tarif ettiğin **tam multimodal anlayış + bölgesel kaynak gösterme + otomatik ret + gerçek yanılgı bankası + sürekli IRT/DIF kalibrasyonu** kombinasyonunu gösteremiyor. Buradaki ürün boşluğu gerçek.

## 9. En doğru geliştirme sırası

İlk iş model seçmek değil, Türkçe altın standart veri kümesi kurmak olmalı:

1. Dijital, taranmış ve hibrit PDF’lerden; ders kitabı, ders notu, rapor ve slayt türlerini kapsayan temsilî sayfalar seç.
2. Metin blokları, okuma sırası, tablolar, grafikler, formüller, şekil ilişkileri ve kaynak bölgelerini çift uzmanla etiketle.
3. Sayfa bazında rastgele bölmek yerine belge/kaynak bazında train–test ayrımı yap; aynı kitabın benzer sayfaları iki tarafa sızmasın.
4. Sonuçları yalnız ortalama olarak değil; tarama kalitesi, alan, dil, layout ve görsel türü dilimlerinde raporla.

Ardından ürün sırası:

- **P0:** Metin + tablo, kazanım planı, sayfa/bölge kaynakları, yapılandırılmış MCQ, deterministik kurallar, uzman ekranı ve CTT pilotu.
- **P1:** Grafik, denklem, şema, karma-modal sorular; görsel gereklilik testi; yanılgı bankası ve madde aileleri.
- **P2:** IRT/DIF, anchor ve pretest tasarımı, maruziyet kontrolü, otomatik form oluşturma ve adaptif uygulama.

Benim kırmızı çizgilerim şunlar olur:

- Kaynak bölgesi olmayan anahtar üretime giremez.
- “Model zor dedi” psikometrik güçlük sayılmaz.
- Aynı şablondan çıkan varyantlar eşdeğer kabul edilmez.
- Tek bir genel VLM bütün belge anlayışından sorumlu tutulmaz.
- Uzman ve öğrenci pilotundan geçmeyen madde yüksek riskli sınavda kullanılmaz.
- Başarı metriği üretilen soru sayısı değil; **değişikliksiz uzman kabulü, doğrulanmış kaynak kapsamı, kalibrasyon belirsizliği, ayırt edicilik, işleyen çeldirici ve DIF güvenliği** olur.

Bu alan çok hızlı değişiyor; yeni araştırmaları düzenli izlemek istersen:






# Proje 2
# Psikometrik Olarak Doğrulanan Otomatik Soru Fabrikası

PDF’den soru üretmek tek başına güçlü bir ürün değildir. Büyük dil modelleri kısa sürede
yüzlerce akıcı soru üretebilir; fakat bu sorular yanlış, belirsiz, kaynaksız, aynı kazanımı tekrar
eden veya kolayca elenebilen çeldiricilere sahip olabilir.
Güçlü ürün, bir “soru üreticisi” değil, uçtan uca bir madde geliştirme ve doğrulama hattı
olmalıdır:
2025 tarihli bir araştırmada örnekli prompting yönteminin, okul kitaplarından üretilen soruların
kapsam, kullanılabilirlik ve Bloom taksonomisine uyumunu iyileştirdiği bulundu. Buna rağmen
araştırma insan değerlendirmesine dayanıyor; gerçek sınavlardaki psikometrik kaliteyi tek
başına kanıtlamıyor. Computers & Education: Artificial Intelligence çalışması
Sağlık eğitimindeki AIG araştırmaları otomatik üretilen soruların bazı koşullarda uzman
sorularına yakın özellikler gösterebildiğini, fakat çeldirici kalitesinin temel sorunlardan biri
olduğunu gösteriyor. Ayrıca aynı şablondan üretilen “eş biçimli” soruların bile aynı güçlüğe sahip
olduğu varsayılamıyor. AIG ve MCQ araştırması · BMC Medical Education araştırması
Ürün örnekleri arasında Kahoot AI, QuestionWell, MagicSchool ve Meazure ADE bulunuyor.
Asıl ürün fırsatı: Öğretmene 100 soru üretmek değil; kaynak gösteren, kapsam dengesi
çıkaran, riskli maddeleri reddeden ve gerçek cevap verisi geldikçe psikometrik özelliklerini
öğrenen güvenilir bir soru bankası oluşturmak.
Başarı ölçütleri: Uzman kabul oranı, kaynak doğruluğu, madde güçlüğü, ayırt edicilik, çeldirici
verimliliği, madde–kazanım uyumu, belirsiz soru oranı ve farklı öğrenci grupları arasındaki
yanlılık.
5. Haftalık çalışma planı motoru
6. PDF içerisindeki metin, tablo ve şekiller anlamlı parçalara ayrılır.
7. Her parça öğrenme kazanımlarıyla eşleştirilir.
8. Hatırlama, uygulama, analiz veya klinik muhakeme gibi hedef bilişsel düzey seçilir.
9. Soru ve cevap yalnızca gösterilen kaynaktan üretilir.
10. Çeldiriciler rastgele değil, öğrencilerin gerçek kavram yanılgılarından oluşturulur.
11. Ayrı modeller doğruluk, belirsizlik, dil, yanlılık ve cevap sızıntısı denetimi yapar.
12. Uzman onayından geçen sorular düşük riskli pilot sınavlarda kullanılır.
13. Gerçek öğrenci cevaplarından güçlük ve ayırt edicilik değerleri hesaplanır.



# Literatür(prompt)
Evet dostum. Ek taramanın ana sonucu oldukça net: Burada tek bir “soru üretme modeli” değil, birbirine bağlı dört sistem inşa etmek gerekiyor:

1. PDF ve görsellerden güvenilir kanıt çıkarma
2. Kanıta dayalı madde geliştirme ve denetleme
3. Öğrencinin bilgisini psikometrik olarak ölçme
4. Ölçüm sonucuna göre öğrenme planını güncelleme

Asıl savunulabilir ürün avantajı da temel LLM modeli değil; kaynak–kazanım grafiği, Türk öğrenci hata bankası, gerçek cevap verisi ve kalite yönetişimi olur.

## 1. Gönderdiğin çalışmaların kritik değerlendirmesi

### Maity, Deroy ve Sarkar, 2025

[Can Large Language Models Meet the Challenge of Generating School-Level Questions?](https://doi.org/10.1016/j.caeai.2025.100370?utm_source=chatgpt.com)

Çalışma, 6–12. sınıf NCERT ders kitaplarından oluşturulmuş 3.502 bağlam–soru örneği üzerinde GPT-4 Turbo, GPT-3.5 Turbo, Gemini Pro, Llama-2-70B ve Llama-3.1-405B gibi modelleri karşılaştırıyor.

Önemli sonuçları:

- Sekiz örnekli prompting, zero-shot üretime kıyasla kapsam, dilbilgisi, kullanılabilirlik, cevaplanabilirlik ve Bloom düzeyi uyumunu artırıyor.
- İyi örnekler modele yalnız soru biçimini değil, ders kitabından hangi tür bilgi seçilmesi gerektiğini de öğretiyor.
- Ancak değerlendirme insan hakemlere dayanıyor.
- Gerçek öğrenci cevapları, madde güçlüğü, ayırt edicilik veya çeldirici davranışı ölçülmüyor.
- Üretilen soruların bazıları verilen bağlamın ötesine geçebiliyor. Dolayısıyla akıcı ve “makul görünen” soru, kaynakla desteklenen soru anlamına gelmiyor.

Ürün açısından doğru çıkarım: Few-shot örnekleme kullanılmalı; fakat örnekler rastgele seçilmemeli. Aynı kazanım, bilişsel işlem, soru tipi ve çözüm yapısına sahip uzman-onaylı maddeler getirilmelidir. Kaynak bağlamının dışına çıkan her öneri otomatik reddedilmelidir.

### Westacott ve arkadaşları, 2023

[Automated Item Generation: impact of item variants on performance and standard setting](https://link.springer.com/article/10.1186/s12909-023-04457-0?utm_source=chatgpt.com)

Bu çalışma özellikle önemli çünkü otomatik üretilmiş “eş biçimli” maddelerin aynı güçlükte olduğu varsayımını gerçek sınav verisiyle sorguluyor.

- 50 ana tıbbi MCQ’dan dört ayrı 50 maddelik form oluşturuluyor.
- 12 İngiltere tıp fakültesinden 2.218 son sınıf öğrencisi çalışmaya katılıyor.
- Maddeler modified Angoff ve klasik test kuramı ölçümleriyle değerlendiriliyor.
- Küçük görünen klinik bağlam değişiklikleri bile madde güçlüğünü ve uzmanların geçme standardını değiştirebiliyor.
- Bazı varyantlarda iki doğru cevap veya belirsiz klinik yorum ortaya çıkmış.
- Çalışmanın gövdesinde 46 madde ailesinin 21’inde güçlük aralığının en az 0,15 olduğu raporlanıyor.

Bu, ürün için kritik bir kural doğuruyor:

> Bir şablondan türetilen maddeler aynı aileye ait olabilir; fakat aynı zorluk parametresini paylaşmamalıdır.

Her çocuk madde pilotlanmalı ve ayrı kalibre edilmelidir. Yeterli veri yoksa aile düzeyindeki parametreden yararlanan hiyerarşik IRT yaklaşımı kullanılabilir; fakat bütün varyantlara tek güçlük değeri atamak güvenli değildir. Aynı aileden birden çok sorunun aynı formda bulunması da yerel bağımsızlığı bozabilir.

### Feng ve arkadaşları, NAACL 2024

[Exploring Automated Distractor Generation for Math Multiple-choice Questions via Large Language Models](https://aclanthology.org/2024.findings-naacl.193/?utm_source=chatgpt.com)

Senin belirttiğin kNN iddiası doğru, ama bağlamını dar tutmak önemli.

Çalışma:

- 10–13 yaş İngilizce matematik öğrencileri için hazırlanmış yaklaşık 1.400 Eedi sorusunu kullanıyor.
- Sorular aritmetik, kesirler ve yuvarlama gibi “Number” konularında.
- Her madde için ortalama yaklaşık 4.000 gerçek öğrenci cevabı bulunuyor.
- kNN ile benzer gerçek soruların prompt örneği olarak seçilmesi; Chain-of-Thought, kural tabanlı üretim, fine-tuning ve örnekleme yöntemleriyle karşılaştırılıyor.
- En iyi kNN sonucu, soru kökü + doğru cevap + hata açıklaması birlikte benzerlik hesabına katıldığında elde ediliyor.
- En iyi ayarda tam eşleşme yaklaşık %10,95; en az bir gerçek çeldiriciyi yakalama yaklaşık %73,85.

Buna rağmen insan değerlendirmesinde gerçek uzman çeldiricileri hâlâ daha iyi:

- Geçerlilik: LLM 3,28; insan 3,99
- İnandırıcılık: LLM 2,68; insan 3,72

Araştırmacıların önemli gözlemi şu: LLM’ler matematiksel olarak mümkün yanlış sonuçlar üretebiliyor; fakat gerçek öğrencilerin hangi yanlışlığı sık yaptığını kendiliğinden bilmiyor.

Çalışmanın sınırlamaları da var:

- Yalnız İngilizce ve dar bir yaş/konu aralığı.
- İnsan değerlendirmesi yalnız 20 soru ve iki değerlendiriciyle yapılmış.
- Exact-match metriği, farklı yazılan fakat aynı yanılgıyı temsil eden cevapları kaçırabiliyor.
- Bazı insan yazımı çeldiriciler de gerçekte çok az öğrenci tarafından seçiliyor.

Dolayısıyla sonuç “her alanda kNN en iyidir” değil. Doğru çıkarım:

> Gerçek öğrenci hatalarından, hedef maddeye bilişsel olarak yakın örnekler getirmek genel amaçlı prompting’den daha değerlidir.

## 2. Türk öğrenci hata ve kavram yanılgısı bankası

Bu gerçekten güçlü bir rekabet avantajı olabilir. Ancak yalnızca “yanlış cevap listesi” olarak tutulmamalı.

Önerilen veri şeması:

- Ders, sınıf ve müfredat sürümü
- Kazanım kimliği
- Alt beceri ve önkoşullar
- Sorunun kanonik çözüm adımları
- Öğrencinin yanlış cevabı
- Hatanın oluştuğu çözüm adımı
- Hata sınıfı:
    - kavram yanılgısı
    - prosedür hatası
    - işaret/hesap hatası
    - soruyu yanlış okuma
    - ölçü birimi hatası
    - dikkatsizlik veya slip
    - eksik önkoşul
- Yanılgının doğal dil açıklaması
- Kaç öğrencide görüldüğü
- Yetenek düzeyine göre görülme oranı
- Seçenek tercih dağılımı
- Öğretmen doğrulaması ve güven puanı
- Tarih, müfredat ve madde sürümü
- Yanılgıya uygulanan müdahale ve sonrasında düzelme oranı

Çeldirici üretim hattı şöyle çalışmalı:

1. Hedef sorunun kazanımı ve çözüm yolu çıkarılır.
2. Benzerlik yalnız metin embedding’iyle değil; kazanım, sembolik çözüm izi, hata adımı, sınıf düzeyi ve hata koduyla hesaplanır.
3. Benzer 3–5 gerçek hata örneği getirilir.
4. Model her çeldirici için bir “yanlış çözüm izi” üretir.
5. Bağımsız çözücü, çeldiricinin gerçekten yanlış fakat makul olduğunu doğrular.
6. Pilot cevaplarından hangi çeldiricinin hangi yetenek grubunca seçildiği ölçülür.
7. İşlemeyen çeldiriciler elenir; yeni gerçek hatalar bankaya geri yazılır.

Burada “hata” ile “kalıcı kavram yanılgısı” ayrılmalıdır. Tek öğrencinin tek seferlik hesap hatasını doğrudan kavram yanılgısı olarak etiketlemek yanlış olur. Yanılgı etiketi için tekrarlı davranış, benzer maddelerde tutarlılık veya öğretmen incelemesi gerekir.

## 3. Ürünlerin teknik olarak sunduğu şeyler

|Ürün|Güçlü olduğu bölüm|Kamuya açık kanıtta eksik olan|
|---|---|---|
|Kahoot AI|Konu, PDF veya URL’den hızlı soru üretimi; öğretmenin düzenleyebilmesi|Kaynak cümlesi doğrulaması, psikometri, DIF, şekil/tablo anlama kanıtı|
|MagicSchool|Sınıf düzeyine göre hızlı MCQ ve cevap anahtarı|Teknik değerlendirme, gerçek öğrenci verisi, provenance ve madde kalibrasyonu|
|QuestionWell|Kazanım/standart filtreleme, kaynak metni gösterme, öğretmen seçimi ve dışa aktarma|Bağımsız psikometrik doğrulama ve gerçek sınav sonuçları|
|Meazure ADE|Kurumsal madde bankası, blueprint, roller, inceleme/onay akışı, sürüm geçmişi ve performans istatistikleri|Otomatik üretimin kendiliğinden kaliteli olduğunu gösteren kanıt değil|

[Kahoot yardım sayfası](https://support.kahoot.com/hc/en-us/articles/40988856361747-How-to-generate-Kahoot-questions-with-AI?utm_source=chatgpt.com), PDF, URL ve konu tabanlı üretimi desteklediğini; fakat AI çıktısının yanlış veya yanlı olabileceğini ve son kontrolün kullanıcı sorumluluğunda olduğunu açıkça belirtiyor. Bu dürüst ama önemli bir sınır.

[MagicSchool MCQ aracı](https://www.magicschool.ai/tools/multiple-choice-quiz-assessment?utm_source=chatgpt.com) daha çok öğretmen üretkenliğine odaklanıyor. Kamuya açık sayfada kaynak cümlesi düzeyinde doğrulama, öğrenci pilotu veya psikometrik kalibrasyon kanıtı bulunmuyor.

[QuestionWell özellikleri](https://questionwell.org/features?utm_source=chatgpt.com), öğrenme çıktılarıyla filtreleme, kaynak metinle bağlantı ve öğretmen düzenleme açısından daha olgun görünüyor. Şirketin 2026 tarihli [sentetik veri ve preference training çalışması](https://questionwell.org/hubfs/Papers/mcq-paper-llncs-main.pdf), SFT ve DPO ile “doğru seçeneğin en uzun olması”, “all/none of the above”, mutlak ifadeler ve boşluk doldurma gibi yüzeysel kusurların azaltılabildiğini gösteriyor. Ancak:

- Çalışma şirket bağlantılı bir ön baskı.
- Yalnız İngilizce.
- 50 quiz/model ve tek üretim prompt’u.
- Değerlendirme ağırlıklı olarak otomatik kurallara dayanıyor.
- Öğrenci performansı ve psikometrik kalite ölçülmüyor.

Buradaki kullanılabilir teknik ders şu: Madde yazım kurallarını makinece ölçülebilir rubric’lere çevirip sentetik tercih çiftleri oluşturmak, ardından SFT/DPO ve son filtreleme uygulamak yüzeysel kusurları azaltabilir. Bu, kaynak doğruluğunu veya iyi ayırt ediciliği tek başına çözmez.

[Meazure ADE](https://www.meazurelearning.com/exam-technology/ade-item-authoring-exam-development?utm_source=chatgpt.com) ise farklı bir sınıfta. Güçlü tarafı AI üretimi değil; rol tabanlı erişim, inceleme–onay iş akışları, blueprint, denetim izi, sürümleme ve performans istatistikleri. Güvenilir sınav ürünü açısından benimsenmesi gereken kurumsal yaklaşım budur.

## 4. Açık uçlu ve el yazılı sınav puanlamada üç ayrı problem

Bunları gerçekten ayırmak gerekiyor.

### A. Yazıyı ve sayfa yapısını tanıma

Bu katman şunları çözer:

- El yazısı OCR/HTR
- Basılı metin
- Matematiksel ifade
- Çizilmiş grafik ve diyagram
- Oklar, silmeler, eklemeler
- Çok sütunlu cevap düzeni
- Cevabın hangi alt soruya ait olduğu

[TrOCR](https://www.microsoft.com/en-us/research/publication/trocr-transformer-based-optical-character-recognition-with-pre-trained-models/) görüntü kodlayıcı–metin çözücü Transformer yaklaşımını kullanıyor. Matematik içinse [MathWriting](https://arxiv.org/abs/2404.10690?utm_source=chatgpt.com) gibi veri kümeleri, sembol dizisinin yanında yazım hareketleri ve yapısal matematik gösteriminin önemini gösteriyor.

Üretim sisteminde:

- Orijinal görüntü saklanmalı.
- OCR metni her zaman bounding box ve güven puanıyla tutulmalı.
- Türkçe karakterler ve matematik sembolleri için ayrı hata raporları çıkarılmalı.
- Düşük güvenli bölge kırpımları VLM’ye ikinci görüş olarak verilebilir.
- OCR ve VLM anlaşamıyorsa otomatik puanlama yapılmamalı.

### B. Cevabın içeriğini puanlama

Kısa cevap, açıklamalı matematik çözümü ve kompozisyon aynı görev değildir.

Her madde için analitik rubric gerekir:

- Beklenen bilgi veya kanıt birimleri
- Kabul edilebilir alternatif çözüm yolları
- Kısmi puan koşulları
- Kritik hata ve takip hatası kuralları
- Sonuç doğru ama gerekçe yanlış durumu
- Birim, gösterim ve yuvarlama toleransları
- Rubric dışı fakat geçerli çözüm için eskalasyon

Genel amaçlı LLM’nin zero-shot puanlamasına güvenilmemeli. [BEA 2024 kısa cevap puanlama çalışması](https://aclanthology.org/2024.bea-1.25/?utm_source=chatgpt.com), sıfır ve az örnekli LLM’lerin alan bilgisi ve muhakeme gerektiren cevaplarda yeterince güvenilir olmadığını gösteriyor.

13.121 öğrenci kompozisyonunda GPT-4o değerlendiren [Scientific Reports çalışması](https://doi.org/10.1038/s41598-024-79208-2?utm_source=chatgpt.com), yaklaşık %30 tam uyum, %77 bir puan toleranslı uyum ve 0,437 QWK buluyor. Ortalama puan yaklaşık 0,9 puan düşük ve bazı öğrenci gruplarında koşullu hata farkları var. Bu, yüksek riskli sınavlarda doğrudan otonom puanlama için yeterli değil.

### C. Operasyonel puanlama yönetişimi

Üçüncü problem modelden çok sınav operasyonudur:

- Kör puanlama
- Çift değerlendirici
- Anlaşmazlık çözümü
- Örnek cevaplarla değerlendirici kalibrasyonu
- Confidence-based abstention
- İtiraz ve yeniden inceleme
- Değiştirilemez denetim izi
- Alt gruplar arasında puanlama hatası
- Rubric ve model sürümleme

Bu nedenle ilk ürün “otomatik not veren sistem” değil, düşük güvenli cevapları insana yönlendiren ve rubric’e göre puan öneren bir değerlendirme yardımcısı olmalıdır.

## 5. IRT ve CAT ile kısa tanılama

IRT/CAT, “öğrencinin zaman içerisindeki öğrenmesi” değil, belirli andaki yeteneğinin verimli ölçümüdür.

2PL modelinde:

Pi(θ)=σ[ai(θ−bi)]P_i(\theta)=\sigma[a_i(\theta-b_i)]

- bib_i: madde güçlüğü
- aia_i: ayırt edicilik
- θ\theta: öğrenci yeteneği

Önerilen süreç:

1. Maddeler önce düşük riskli pilotta kullanılır.
2. Ortak anchor maddelerle ölçek eşitleme yapılır.
3. 1PL/Rasch veya 2PL kalibre edilir.
4. 3PL yalnız yeterli örneklem ve gerçek tahmin davranışı varsa değerlendirilir.
5. CAT başlangıcında EAP/MAP tahmini kullanılır.
6. Madde yalnız maksimum bilgiye göre değil; blueprint, maruz kalma ve güvenlik kısıtlarıyla seçilir.
7. Standart hata veya sınıflandırma güveni yeterli olduğunda test durdurulur.

[Shadow-test yaklaşımı](https://journals.sagepub.com/doi/10.3102/10769986029003273?utm_source=chatgpt.com), her adımda bütün içerik ve maruz kalma kısıtlarını karşılayan tam bir test oluşturup içinden en uygun sonraki maddeyi seçmeye dayanıyor. Bu, sırf en yüksek Fisher bilgisine bakmaktan daha güvenlidir.

Önemli ölçütler:

- θ\theta bias ve RMSE
- Güven aralığı kapsama oranı
- Ortalama test uzunluğu
- Sınıflandırma duyarlılığı/özgüllüğü
- Blueprint ihlalleri
- Madde maruz kalma oranı ve test örtüşmesi
- Havuz kullanım dengesi
- Madde fit ve parametre drift’i
- Yerel bağımlılık
- Madde ailesi içi zorluk varyansı

Otomatik üretilmiş maddeler kalibre edilmeden CAT havuzuna girmemelidir.

## 6. BKT, DKT, AKT ve bilişsel tanı modelleri

Bu modeller aynı şeyi yapmaz.

### BKT

Bayesian Knowledge Tracing, her beceri için bilme/bilmeme durumunu gizli Markov modeliyle izler.

Avantajları:

- Açıklanabilir
- Az veriyle başlayabilir
- Öğretmene gösterilebilir
- Slip, guess, öğrenme ve başlangıç hâkimiyeti parametreleri nettir

İlk sürüm için en güvenli tercih budur.

### DKT

[Deep Knowledge Tracing](https://proceedings.neurips.cc/paper_files/paper/2015/hash/bac9162b47c56fc8a4d2a519803d51b3-Abstract.html?utm_source=chatgpt.com), öğrenci etkileşim dizisini RNN ile modeller. Karmaşık örüntüleri öğrenebilir; ancak açıklanması ve kalibre edilmesi daha zordur.

### AKT

[Attentive Knowledge Tracing](https://kdd.org/kdd2020/accepted-papers/view/context-aware-attentive-knowledge-tracing.html?utm_source=chatgpt.com), dikkat mekanizması, zaman/bağlam uzaklığı ve Rasch benzeri soru güçlüğü bileşenleri kullanır. Uzun diziler ve beceriler arası ilişkilerde avantaj sağlayabilir.

### Bilişsel tanı modelleri

[G-DINA](https://doi.org/10.1007/s11336-011-9207-7), öğrenciyi tek bir genel yetenek yerine beceri hâkimiyeti profiliyle tanımlar. Bunun için güvenilir bir Q-matrix gerekir: Hangi madde hangi becerileri gerektiriyor?

Q-matrix uzman tarafından hatalı hazırlanırsa tanı da hatalı olur. Ampirik Q-matrix doğrulama çalışmaları, uzman belirlemesinin mutlaka cevap verisiyle sınanması gerektiğini gösteriyor.

Önerim:

- Başlangıç: BKT + kalibre edilmiş madde güçlüğü
- İyi bir Q-matrix varsa: G-DINA
- Yeterli zaman serisi oluştuktan sonra challenger olarak simpleKT/AKT
- DKT’yi varsayılan seçim yapmamak

[pyKT karşılaştırması](https://papers.nips.cc/paper_files/paper/2022/hash/75ca2b23d9794f02a92449af65a57556-Abstract-Datasets_and_Benchmarks.html?utm_source=chatgpt.com), hatalı veri bölme ve değerlendirme yöntemlerinin label leakage yarattığını; daha karmaşık modellerin avantajlarının bazen abartıldığını gösteriyor.

AUC tek başına yeterli değildir. Log loss, Brier score, kalibrasyon hatası, öğrenci-disjoint ve zaman bazlı holdout, cold-start, nadir kazanımlar ve alt grup performansı ölçülmelidir.

## 7. Önkoşul bilgi grafiği

Grafiğin ilk sürümü yalnızca LLM tarafından çıkarılmamalı.

Önerilen yapı:

- Düğüm: kazanım, kavram, prosedür veya temsil biçimi
- Kenar:
    - zorunlu önkoşul
    - yardımcı önkoşul
    - eş zamanlı beceri
    - kavram yanılgısı bağımlılığı
- Her kenar için:
    - güven puanı
    - kaynak
    - öğretmen onayı
    - müfredat sürümü
    - davranışsal kanıt

[PREAP çalışması](https://link.springer.com/article/10.1007/s10758-023-09682-6?utm_source=chatgpt.com), ders kitaplarında önkoşul ilişkisinin insan tarafından etiketlenmesinin bile zor ve protokol gerektiren bir görev olduğunu gösteriyor. [NAACL 2021 çalışması](https://aclanthology.org/2021.naacl-main.164/?utm_source=chatgpt.com) ise metinsel ve ilişkisel özellikleri heterojen grafik sinir ağlarıyla birleştiriyor.

En güvenli yöntem:

1. MEB müfredatı ve öğretmenlerden başlangıç grafiği
2. Ders kitabından LLM tarafından kenar önerileri
3. Soru cevap örüntülerinden davranışsal destek
4. Uzman incelemesi
5. Müdahale verisiyle doğrulama

“B kitabında A’dan sonra geliyor” önkoşul kanıtı değildir. Yanıt korelasyonu da nedensellik değildir. Nihai doğrulama, A öğretilince B başarısının gerçekten artıp artmadığıdır.

## 8. Unutma ve spaced repetition

Basit başlangıç modeli:

P(hatırlama)=2−Δt/hP(\text{hatırlama})=2^{-\Delta t/h}

Burada hh, öğrenci–beceri veya öğrenci–madde için tahmini yarı ömürdür. Doğru cevaplar yarı ömrü yükseltir, hatalar düşürür.

Yaklaşık 50.700 sürücü sınavı öğrencisiyle yapılan [randomize kontrollü çalışma](https://www.nature.com/articles/s41539-021-00105-8?utm_source=chatgpt.com), unutma modeline dayalı seçim algoritmasının, çalışma süresi ve sıklığı kontrol edildiğinde tahmini hatırlama süresini yaklaşık %69 artırdığını bildiriyor. Bununla birlikte alan yetişkin sürücü sınavı ve çoktan seçmeli sorularla sınırlı.

[DAS3H](https://arxiv.org/abs/1905.06873?utm_source=chatgpt.com) gibi modeller, tekil kart hafızası yerine birden fazla beceri üzerindeki öğrenme ve unutmayı birlikte modellemeye çalışıyor.

Ürün açısından:

- Olgu ve kelime bilgisi için madde düzeyinde yarı ömür
- Matematik ve kavramsal alanlarda beceri düzeyinde unutma
- Aynı soruyu tekrar göstermek yerine farklı temsillerle retrieval practice
- Öğrenildi sanılan konular için gecikmeli probe maddeleri
- Yanlış cevap sonrası doğrudan tekrar yerine düzeltici açıklama + aralıklı yeniden ölçme

Metrikler:

- Brier score ve log loss
- Kalibrasyon
- 7/14/30 günlük gecikmeli hatırlama
- Öğrenme kazanımı/dakika
- Aynı kazanım için gereken tekrar sayısı
- Programa uyum ve bırakma oranı

## 9. Sınav ağırlığı, süre ve müsaitlikle plan optimizasyonu

İlk sürümde reinforcement learning yerine açıklanabilir MILP veya CP-SAT kullanmak daha doğru olur.

Karar değişkeni:

xi,t=1x_{i,t}=1

öğrenme etkinliği ii, zaman dilimi tt’ye atanmışsa.

Amaç fonksiyonu kabaca:

max⁡∑xi,t(sınav ag˘ırlıg˘ı×o¨g˘renme kazanımı^×sınav gu¨nu¨ndeki kalıcılık−yorgunluk−gec¸is¸ maliyeti−belirsizlik)\max \sum x_{i,t} (\text{sınav ağırlığı} \times \widehat{\text{öğrenme kazanımı}} \times \text{sınav günündeki kalıcılık} -\text{yorgunluk} -\text{geçiş maliyeti} -\text{belirsizlik})

Kısıtlar:

- Öğrencinin boş zamanı
- Sınav tarihleri
- Günlük ve oturumluk azami süre
- Önkoşul sırası
- Ders/kazanım/Bloom kotası
- Spacing aralıkları
- Dinlenme
- Erişilebilirlik ve cihaz koşulları
- Madde maruz kalma sınırı
- Öğretmenin zorunlu tuttuğu etkinlikler

Zaman belirsizliği altında öğrenme yolu optimizasyonu yapan Expert Systems çalışması, beklenen başarı ile gereken zamanı birlikte ele alıyor. Contextual bandit ve RL daha sonra değerlendirilebilir; fakat bunun için randomize keşif verisi, güvenli off-policy evaluation ve doğru tanımlanmış nedensel ödül gerekir.

“Uygulamayı tamamladı” ödülü, “öğrendi” ödülü değildir.

## 10. Haftalık yeniden ölçme döngüsü

İyi bir kapalı döngü:

1. Öğrenci çalışır.
2. Doğruluk, süre, güven, ipucu kullanımı ve çözüm yolu kaydedilir.
3. Düşük güvenli OCR veya puanlar insana yönlendirilir.
4. IRT öğrenci yeteneğini günceller.
5. BKT/CDM kazanım hâkimiyetini günceller.
6. Unutma modeli hatırlama olasılığını günceller.
7. Önkoşul grafiği zayıflığın olası kök nedenlerini gösterir.
8. Planlayıcı sonraki yedi günü yeniden optimize eder.
9. Bir miktar anchor/probe ve keşif sorusu korunur.
10. Sonraki hafta model tahminleri gerçek sonuçla karşılaştırılır.

Keşif soruları bırakılmazsa sistem yalnız zaten zayıf sandığı konuları sorar ve kendi inancını doğrulayan bir geri besleme döngüsüne girer.

## 11. PDF, tablo, şekil ve formülleri gerçekten anlama

Tek bir VLM’ye bütün sayfayı gönderip açıklamasını istemek yeterli değil. Önce doküman grafiği kurulmalı:

```
Belge
 └─ Sayfa
     ├─ Metin bloğu
     ├─ Tablo
     │   ├─ Başlık hücreleri
     │   ├─ Veri hücreleri
     │   ├─ Birimler
     │   └─ Dipnot
     ├─ Şekil
     │   ├─ Kırpılmış görüntü
     │   ├─ Başlık
     │   ├─ Etiketler
     │   └─ Metindeki atıflar
     └─ Denklem
         ├─ Görüntü
         └─ LaTeX/MathML
```

[Docling teknik raporu](https://research.ibm.com/publications/docling-technical-report?utm_source=chatgpt.com), layout modelleri ve TableFormer ile belge yapısını çıkarmaya odaklanıyor. [OmniDocBench](https://openaccess.thecvf.com/content/CVPR2025/html/Ouyang_OmniDocBench_Benchmarking_Diverse_PDF_Document_Parsing_with_Comprehensive_Annotations_CVPR_2025_paper.html?utm_source=chatgpt.com), farklı belge türlerinde hiçbir ayrıştırıcının bütün düzen, tablo ve formül koşullarında tek başına yeterli olmadığını gösteriyor.

### Tablolar

Tablo yalnız düz metne çevrilmemeli. Şunlar korunmalı:

- Satır ve sütun başlıkları
- Birleştirilmiş hücreler
- Birimler
- Hiyerarşik başlıklar
- Dipnot ve istisnalar
- Hücrenin sayfadaki koordinatı
- Orijinal tablo kırpımı

[PubTables-1M](https://www.microsoft.com/en-us/research/publication/pubtables-1m/?utm_source=chatgpt.com) ve [Table Transformer](https://github.com/microsoft/table-transformer?utm_source=chatgpt.com) yaklaşımları tespit ve yapı tanıma için kullanılabilir.

### Grafikler

Grafik önce türüne göre ayrılmalı:

- Çubuk
- Çizgi
- Pasta
- Dağılım
- Box plot
- Harita
- Süreç veya kavram diyagramı

[DePlot](https://aclanthology.org/2023.findings-acl.660/?utm_source=chatgpt.com), grafiği doğrusal bir tablo gösterimine çevirip ardından dil modeliyle soru cevaplama yaklaşımını kullanıyor. Üretimde hem çıkarılmış veri tablosu hem de orijinal grafik kırpımı modele verilmelidir.

### Diyagram ve fotoğraflar

VLM şunları çıkarmalı:

- Nesneler ve etiketler
- Ok yönleri
- Parça–bütün ilişkileri
- Süreç sırası
- Mekânsal ilişkiler
- Şekil açıklaması
- Metinde şekle yapılan atıflar

Ancak şeklin içinde bulunmayan alan bilgisiyle yorum yapmasına izin verilmemelidir.

### Formüller

Formül için:

- Görüntü kırpımı
- LaTeX/MathML gösterimi
- Sembol tanımları
- Önceki ve sonraki açıklama
- Denklem numarası
- Birim ve koşullar

birlikte saklanmalıdır.

## 12. “Önemli yer” analizi

Bunu tek bir modele “Bu PDF’de önemli yerler nereler?” diye sorarak yapmak zayıf olur.

Her bilgi birimi için öncelik puanı hesaplanabilir:

Priority(u)=w1mu¨fredat ag˘ırlıg˘ı+w2kazanım es¸les¸mesi+w3o¨nkos¸ul merkezilig˘i+w4pedagojik rol+w5o¨g˘retmen/sınav kanıtı+w6deg˘erlendirilebilirlik−w7tekrarPriority(u)= w_1\text{müfredat ağırlığı} +w_2\text{kazanım eşleşmesi} +w_3\text{önkoşul merkeziliği} +w_4\text{pedagojik rol} +w_5\text{öğretmen/sınav kanıtı} +w_6\text{değerlendirilebilirlik} -w_7\text{tekrar}

Pedagojik roller:

- Tanım
- İlke veya yasa
- İşlem/prosedür
- Çalışılmış örnek
- Neden–sonuç
- Karşılaştırma
- İstisna
- Sık hata
- Tablo/şekil yorumu
- Bölüm özeti

Ancak maddeler yalnız en yüksek puanlı parçalardan seçilmemeli. Blueprint optimizasyonu şu kısıtları sağlamalı:

- Zorunlu bütün kazanımlar kapsansın.
- Bloom dağılımı hedefe uysun.
- Aynı kazanım gereğinden fazla tekrar edilmesin.
- Tablo, şekil ve uygulama sorularına kota ayrılsın.
- İstisnalar ve yaygın yanılgılar kaybolmasın.
- Her seçim için öğretmene “neden önemli” ve kaynak kanıtı gösterilsin.

## 13. Üretici–çözücü–eleştirici hattı

Önerdiğin ayrım doğru. Fakat rollerin girdileri farklı olmalı.

### Üretici

Şunları görür:

- Kazanım
- Bloom düzeyi
- Soru tipi
- Zorluk hedefi
- Kanıt paketi
- Benzer uzman maddeleri
- Gerçek hata örnekleri

Çıktısı:

- Soru kökü
- Doğru cevap
- Çeldiriciler
- Çözüm
- Her iddia için kaynak kimliği
- Her çeldirici için yanlış çözüm izi
- Tahmini riskler

### Bağımsız çözücü

Doğru cevap etiketini ve üreticinin açıklamasını görmez. Soruyu kanıttan yeniden çözer ve cevabını kaynak göstererek verir.

Kontrol edilir:

- Aynı cevaba ulaştı mı?
- Kaynak paketi soruyu cevaplamaya yetiyor mu?
- Birden fazla seçenek savunulabiliyor mu?
- Cevap için dış bilgi gerekiyor mu?

### Eleştirici

Şunları denetler:

- Kaynak dışı iddia
- Belirsiz veya eksik soru
- Birden fazla doğru cevap
- Hiç doğru cevap olmaması
- Dil ve okuma düzeyi
- Kültürel veya demografik yanlılık
- Seçenek uzunluğu ipucu
- Dilbilgisel uyum ipucu
- Kök ile doğru seçenek arasındaki aşırı kelime örtüşmesi
- “Her zaman/asla” gibi yüzeysel ipuçları
- Aynı kazanımın tekrarı

Aynı model ailesinin üç kez çağrılması tam bağımsızlık sağlamaz; hatalar korelasyonlu olabilir. Mümkünse farklı model ailesi, farklı prompt ve deterministik araç kontrolü kullanılmalı. Zayıf self-verification’ın güvenilir olmadığı, daha güçlü dış doğrulayıcının gerektiği [ACL 2024 çalışmasında](https://aclanthology.org/2024.findings-acl.924/?utm_source=chatgpt.com) da görülüyor.

## 14. Benzerlik, sızıntı ve güvenlik kontrolü

Üç farklı problem ayrı çözülmeli:

### İç tekrar ve klon kontrolü

- MinHash/n-gram
- BM25
- Embedding benzerliği
- Sayı, değişken ve isimleri normalize ederek yeniden karşılaştırma
- Formül ve çözüm ağacı benzerliği
- Aynı soru ailesinden maddelerin aynı forma gelmesini engelleme

### Cevap ipucu sızıntısı

- Doğru seçeneğin sürekli daha uzun olması
- Kökle yüksek kelime örtüşmesi
- Dilbilgisel olarak yalnız bir seçeneğin uyması
- Kategorik kapsam farkı
- “Yukarıdakilerin hepsi/hiçbiri”
- Görsel üzerindeki etiketin cevabı doğrudan vermesi
- Açıklamanın veya dosya adının cevap içermesi

### Kamuya veya öğrencilere sızmış madde

- Tuzlanmış madde parmak izi
- Tam ve anlamsal benzerlik indeksi
- Yetkili web/koleksiyon taraması
- Olağandışı doğru cevap ve süre örüntüleri
- Bir grubun aniden çok kısa sürede tam başarı göstermesi
- Madde parametresi drift’i

Benchmark contamination çalışmaları, yalnız exact-match kontrolünün yeterli olmadığını gösteriyor; örneğin [PaCoST](https://aclanthology.org/2024.findings-emnlp.97/?utm_source=chatgpt.com) eşleştirilmiş varyantlar üzerinden model güvenindeki farkları kullanıyor. Bu teknik doğrudan sınav sızıntısı çözümü değildir ama normalleştirilmiş varyant ve davranışsal anomali kontrollerinin önemini gösterir.

## 15. Ölçülmesi gereken metrikler

### PDF ve multimodal ayrıştırma

- Metin: CER, WER
- Layout: bölge mAP/F1
- Okuma sırası: pairwise accuracy veya Kendall korelasyonu
- Tablo: GriTS/TEDS, hücre F1, sayısal doğruluk
- Grafik: plot-to-table doğruluğu ve grafik QA
- Formül: normalize exact match, sembol/yapı edit mesafesi
- Şekil–başlık bağlantısı: precision/recall/F1
- Kaynak kutusu: bounding-box IoU
- Uçtan uca kanıt geri çağırma oranı

### Pilot öncesi madde kalitesi

- Kaynak doğruluğu ve kapsamı
- Kaynak–iddia entailment
- Cevaplanabilirlik
- Tek doğru cevap oranı
- Belirsiz madde oranı
- Kazanım ve Bloom uzman uyumu
- Blueprint sapması
- Yinelenen madde oranı
- Uzman kabul oranı
- Uzmanın düzenleme süresi
- Kaynak dışı bilgi oranı

### Pilot sonrası

- Madde güçlüğü
- Point-biserial ayırt edicilik
- Çeldirici seçim oranı
- Yetenek bandına göre seçenek eğrileri
- İşlevsiz çeldirici oranı
- IRT a,b,ca,b,c parametreleri
- Madde ve test bilgi fonksiyonu
- Item fit
- Yerel bağımlılık
- Madde ailesi varyansı
- Drift
- Maruz kalma

### DIF ve adalet

- Mantel–Haenszel
- Lojistik regresyon DIF
- IRT likelihood-ratio DIF
- Etki büyüklüğü
- Koşullu hata oranları
- Alt gruplarda yanlış puanlama ve abstention oranı

DIF “madde kesin yanlıdır” sonucu vermez; aynı yetenek düzeyindeki gruplar arasında beklenmeyen farkı işaretler. İçerik uzmanı incelemesi gerekir. DIF bulunmaması da otomatik olarak adalet kanıtı değildir.

## 16. Önerdiğim geliştirme sırası

### İlk ürün

- PDF belge grafiği
- Metin, tablo, şekil ve formül provenance’ı
- Kazanım ve blueprint editörü
- Kaynağa bağlı MCQ üretimi
- Üretici–bağımsız çözücü–eleştirici
- Öğretmen onayı ve denetim izi
- Uzman kabul/düzenleme ölçümü

### İkinci aşama

- Türk öğrenci hata bankası
- Çözüm adımı ve hata kodu tabanlı retrieval
- Düşük riskli pilotlar
- CTT ve çeldirici analizi
- Madde ailesi ve klon yönetimi

### Üçüncü aşama

- Anchor’lı IRT kalibrasyonu
- CAT ve shadow-test
- DIF, drift ve exposure kontrolleri
- BKT/G-DINA öğrenci modeli
- Önkoşul grafiği

### Sonraki aşama

- El yazılı cevaplarda OCR + rubric destekli puan önerisi
- Confidence-based human review
- Unutma modeli
- Kısıtlı haftalık planlayıcı
- Randomize müdahale deneyleri
- Yeterli veri oluşursa AKT/contextual bandit challenger modelleri

Ben ilk sürümde MCQ, açık uçlu otonom puanlama, CAT, knowledge tracing ve kişisel planlamayı aynı anda çıkarmaya çalışmazdım. Hepsinin ortak temeli olan kanıt grafiği, veri sözleşmesi, madde sürümleme ve öğrenci cevap telemetrisi önce kurulmalı.