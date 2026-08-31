## Net karar

Senin kullanımın için en doğru temel mimari:

> **Uyarlamalı + multimodal + hiyerarşik + hibrit RAG**

Yani tek başına GraphRAG veya serbest çalışan Agentic RAG değil. Bunlar birbirinin alternatifi de değil:

- **GraphRAG**, bilginin nasıl ilişkilendirileceğini ve getirileceğini tanımlar.
- **Agentic RAG**, hangi aramanın ne zaman ve kaç tur yapılacağını yöneten kontrol katmanıdır.
- **RAPTOR**, uzun kitapları bölüm–ünite–kitap düzeyinde hiyerarşik özetler.
- **Multimodal RAG**, metinle beraber şekil, tablo, grafik ve sayfa düzenini kullanır.
- **Hybrid RAG**, BM25 gibi sözcüksel arama ile anlamsal vektör aramasını birleştirir.

Her soruya GraphRAG ya da agentic süreç uygulamak kaliteyi artırmaz; maliyeti, gecikmeyi ve hata yüzeyini büyütür. Özellikle yakın tarihli bir ders kitabı GraphRAG benchmarkında bazı graph yöntemleri yapısal gürültü nedeniyle üretimi kötüleştirmiş, RAPTOR kitap hiyerarşisine daha iyi uyum göstermiş ve matematik görevlerinde graph yaklaşımlarının tamamında gerilemeler görülmüştür. Bu çalışma henüz preprint düzeyindedir ama önemli bir uyarıdır. [GraphRAG-Bench](https://arxiv.org/abs/2506.02404)

## Gönderdiğin veri hakkında önemli bulgular

İncelediğim dosyalar şu an farklı benchmark görevlerine hizmet edebilir:

|Dosya|Kullanım|Mevcut risk|
|---|---|---|
|kitap.pdf|187 sayfalık ana bilgi kaynağı; metin, tablo, şekil, ünite soruları|Son sayfalardaki cevap anahtarı retrieval’dan ayrılmalı|
|02_t03jdet2c4r.pdf|Konu özeti ve ikincil kaynak karşılaştırması|Düz metin çıkarmada sütunların sırası karışıyor; layout parser gerekli|
|`2.jpg`|Çalışma defteri örneği|Şu anda tam çalışma defteri değil, yalnızca bir sayfa|
|Üç PNG|Görsel soru ve etkinlik smoke testi|Üç örnek istatistiksel benchmark için yetersiz|
|sorular.json|Soru manifesti|798 kayıtta soru metni yok; 434 görsel referansı var fakat görsellerin çoğu yok; bütün `kazanimlar` alanları boş|
|kazanimlar.json|Müfredat grafiğinin başlangıcı|29 kazanım mevcut; soru–kazanım eşlemeleri henüz yok|

`sorular.json` içindeki `cevap` alanı bütün kayıtlarda mevcut. Ancak 147 kayıtta `cevap_harf` boş; bunlar açık uçlu veya farklı soru tipleri olabilir. Asıl kritik eksiklik soru gövdeleri ve seçenekleridir. Dolayısıyla şu anda “798 soruluk benchmark” değil, “798 soruluk cevap ve varlık manifesti” vardır.

Ayrıca kitapta bulunan:

- Ünite sonu soruları,
- Soruların geçtiği sayfalar,
- Cevap anahtarı,
- Konu özetlerinde yazılı cevaplar

soru çözme benchmarkının retrieval indeksinden çıkarılmalıdır. Sadece öğretici konu içeriği aranabilir olmalıdır. Aksi hâlde ölçülen şey akıl yürütme değil, cevap sızıntısı olur.

## Önerdiğim sistem mimarisi

```
flowchart TD
    A["Kaynak derleyici"] --> B["Sürümlü kanıt deposu"]
    B --> C["BM25 + dense + görsel + graph/tree indeksleri"]
    C --> D{"Görev yönlendirici"}
    D -->|Kesin metin| E["Hybrid retrieval + reranker"]
    D -->|Şekil veya tablo| F["Görsel + metin retrieval"]
    D -->|Çok adımlı| G["Graph / IRCoT: en fazla 3 tur"]
    D -->|Ünite veya kitap özeti| H["RAPTOR hiyerarşisi"]
    E --> I["Kanıt paketi"]
    F --> I
    G --> I
    H --> I
    I --> J["Göreve özel üretici"]
    J --> K["İddia ve atıf denetimi"]
    K --> L["Cevap, soru veya özet / çekimser kal"]
```

### 1. Kaynak derleyici

PDF’yi doğrudan parçalayıp vektör veritabanına atmak yeterli değil. Derleyicinin her sayfada şunları çıkarması gerekir:

- Başlık, alt başlık ve ünite hiyerarşisi
- Paragraf ve liste sınırları
- Tablo hücreleri ve satır–sütun ilişkileri
- Şekil, grafik ve diyagram bölgeleri
- Şekil başlığı ve şekle gönderme yapan paragraflar
- Soru gövdesi, seçenekler ve cevap alanı
- Sayfa numarası ve her öğenin koordinatı
- Kazanım, sınıf, ders, ünite, konu ve kaynak sürümü
- Kaynak türü: ders kitabı, özet, öğretmen notu, soru bankası, cevap anahtarı

Önerilen veri katmanları:

- **Ham katman:** Orijinal PDF ve görsel, SHA-256 kaynak kimliğiyle.
- **Ayrıştırılmış katman:** Sayfa öğeleri, koordinatlar, OCR güven puanı.
- **Doğrulanmış katman:** Öğretmen onaylı kavramlar, ilişkiler, kazanımlar, sorular ve çözüm kanıtları.

Gönderdiğin kitap native text içeriyor; bu nedenle önce PyMuPDF/pdfplumber benzeri deterministik çıkarım kullanılmalı. OCR yalnızca metnin bozuk veya görsel içinde olduğu bölgelerde çalışmalı. Layout için Docling/MinerU/PaddleOCR ailesi ayrı ayrı ölçülmeli. OmniDocBench; metin, okuma sırası, tablo, formül ve layout’u ayrı değerlendirdiği ve genel VLM’lerin her zaman uzman parserlardan daha iyi olmadığını gösterdiği için iyi bir değerlendirme çerçevesidir. [OmniDocBench](https://arxiv.org/abs/2412.07626), [Docling teknik raporu](https://arxiv.org/abs/2408.09869)

### 2. Tek tür chunk yerine eşzamanlı öğrenme birimleri

Aynı kaynaktan birden fazla temsil üret:

|Temsil|Başlangıç boyutu|Kullanım|
|---|---|---|
|Atomik önerme|Tek doğrulanabilir iddia|Kesin bilgi ve atıf|
|Çocuk chunk|150–300 Türkçe token|Normal kitap QA|
|Üst bölüm|700–1.500 token|Bağlam genişletme|
|Tablo nesnesi|Yapısal JSON/HTML + görüntü|Tablo soruları|
|Görsel nesne|Kırpılmış görüntü + caption + ilgili metin|Diyagram/şekil QA|
|Sayfa görüntüsü|Tam sayfa|Görsel retrieval|
|Ünite özeti|Bölüm bazlı|Global soru ve özet|
|Kitap ağacı|Ünite–konu–alt konu|RAPTOR/global retrieval|

Atomik önerme retrieval’ı kesin iddialarda avantaj sağlayabilir; Dense X Retrieval çalışmasında proposition düzeyindeki birimler passage tabanlı retrieval’a göre önemli recall artışları sağlamıştır. Ancak atomik önerme mutlaka ana paragrafı ve sayfa görüntüsüne bağlanmalıdır; tek başına gönderilirse bağlam kaybı oluşur. [Dense X Retrieval](https://aclanthology.org/2024.emnlp-main.845/)

ColBERTv2’nin token düzeyindeki late-interaction yaklaşımı ince kavramsal eşleşmeler için güçlü bir deney koludur. [ColBERTv2](https://aclanthology.org/2022.naacl-main.272/?utm_source=chatgpt.com)

### 3. İndeks yapısı

Her embedding modeli sürümü için ayrı indeks oluştur. Bütün sınıfları tamamen ayrı veritabanlarına bölmek gerekmez; fakat retrieval’dan önce zorunlu metadata filtresi uygulanmalıdır:

```
müfredat_sürümü
→ sınıf
→ ders
→ ünite
→ kazanım
→ yetkili kaynak türleri
```

Örneğin 12. sınıf biyoloji sorusu, özellikle istenmedikçe 8. sınıf fen veya üniversite kaynağına düşmemelidir.

Önerdiğim altyapı:

- **PostgreSQL:** kaynak, sürüm, kazanım, soru ve denetim kayıtlarının doğruluk kaynağı
- **OpenSearch:** BM25, filtreleme, Türkçe normalizasyon ve sözcüksel retrieval
- **Qdrant veya Milvus:** dense ve multivector indeksler
- **S3/MinIO:** PDF, sayfa görüntüsü ve region crop deposu
- **PostgreSQL edge tablosu:** ilk curriculum graph
- **Neo4j:** ancak graph sorgularının ölçülebilir yararı kanıtlanırsa
- **OpenTelemetry + deney deposu:** her cevabın retrieval ve model izleri

Türkçe için:

- Unicode NFC normalizasyonu,
- `I/ı` ve `İ/i` dönüşümlerinin doğru yapılması,
- Satır sonu hece bölünmelerinin temizlenmesi,
- Bilimsel simge ve alt indislerin korunması,
- Hem özgün hem normalize edilmiş metin alanlarının indekslenmesi,
- DNA/deoksiribonükleik asit gibi sürümlü eşanlam sözlüğü

gerekir. Aşırı kök bulma biyolojik terimleri bozabileceği için BM25 alanlarından en az biri köklenmemiş tutulmalıdır.

## Retrieval ve reranking’in ayrıntılı akışı

### Aşama 0 — Kapsam ve görev sınıflandırması

Sistem önce şunları belirlemeli:

- Öğrenci hangi sınıf ve derste?
- Soru hangi müfredat sürümüne ait?
- Soru metinsel mi, görsel mi?
- Tek kanıt mı yoksa birkaç kanıt mı gerekiyor?
- “Kitaptaki X nedir?” mi, “ünitenin genel mantığı nedir?” mi?
- Kaynakta cevaplanabilir mi?
- Kullanıcı soru çözdürüyor mu, yeni soru mu ürettiriyor?

Bu yönlendirme küçük bir modelle veya başlangıçta kurallarla yapılabilir. Adaptive-RAG, sorunun karmaşıklığına göre retrieval olmadan, tek-adımlı veya çok-adımlı retrieval arasında seçim yapmanın kalite–maliyet dengesini iyileştirdiğini göstermiştir. [Adaptive-RAG](https://aclanthology.org/2024.naacl-long.389/)

### Aşama 1 — Paralel aday üretimi

Başlangıç ayarı olarak:

- BM25: ilk 40–50
- Dense embedding: ilk 40–50
- BGE-M3 sparse veya başka neural sparse kanal: ilk 30–40
- Görsel retrieval: görsel soruysa ilk 15–20
- Graph adayları: multi-hop sorudaysa ilk 15 kavram/düğüm

Sonuçlar Reciprocal Rank Fusion ile birleştirilebilir:

RRF⁡(d)=∑iwi60+rank⁡i(d)\operatorname{RRF}(d)=\sum_i \frac{w_i}{60+\operatorname{rank}_i(d)}

Buradaki `60` ve ağırlıklar yalnızca başlangıç değeridir; gizli geliştirme setinde ayarlanmalıdır.

BGE-M3, 100’den fazla dilde dense, sparse ve multi-vector retrieval’ı aynı model ailesinde destekliyor ve 8.192 token uzunluğa kadar çalışıyor. Makalede uzun belge görevlerinde hibrit kullanım tek dense kanaldan daha güçlü. Bu yüzden çok iyi bir baseline’dır. [BGE-M3](https://aclanthology.org/2024.findings-acl.137/)

### Aşama 2 — Reranking

Birleşmiş ilk 50–80 aday:

1. Cross-encoder/LLM reranker ile yeniden sıralanır.
2. İlk 8–12 kanıt seçilir.
3. Gerekli iddiaların tamamını kapsayıp kapsamadığı denetlenir.
4. Aynı paragrafın beş benzer varyantı yerine kanıt çeşitliliği sağlanır.
5. Gerekliyse üst paragraf ve komşu sayfa eklenir.

Reranker sorgusuna yalnızca soru değil şunlar da verilmeli:

```
Görev: 12. sınıf biyoloji kitap sorusu
Kazanım: 12.1.x.x
Beklenen kanıt: mekanizma ve neden-sonuç
Aday: başlık + paragraf + caption + sayfa bilgisi
```

### Aşama 3 — Kanıt yeterliliği

Modelin “eminim” demesi güven ölçüsü değildir. Güven şu sinyallerden kalibre edilmelidir:

- Gold’e göre retrieval coverage
- Reranker skor marjı
- Birden fazla retrieval kanalının uzlaşması
- İddia denetleyicisinin support skoru
- İki bağımsız çözücünün anlaşması
- Kaynaklar arasında çelişki olup olmaması

Kalibrasyon için isotonic regression veya Platt scaling kullanılabilir. Kaynak yetersizse sistem:

- Bir kez sorgu yeniden yazabilir,
- En fazla 2–3 retrieval turu yapabilir,
- Sonra “bu kaynaklarda yeterli kanıt yok” diyebilmelidir.

Kapalı MEB kaynak modunda CRAG makalesindeki gibi internete açılmak yerine çekimser kalınmalıdır. [CRAG](https://arxiv.org/abs/2401.15884?utm_source=chatgpt.com)

## GraphRAG tam olarak nerede kullanılmalı?

Curriculum graph’ın doğrulanmış omurgası deterministik olmalı:

```
Sınıf → Ders → Ünite → Konu → Kazanım
Kavram → önkoşul / parçası / nedenidir / karşıtıdır
Örnek → kavramı örnekler
Yanlış inanış → kavramla çelişir
Soru → kazanımı ölçer
Çeldirici → yanlış inanışı temsil eder
İddia → kaynak sayfa ve koordinat tarafından desteklenir
```

LLM’nin çıkardığı yeni ilişkilere doğrudan “doğru” statüsü verilmemeli; `candidate_edge` olarak saklanmalı ve öğretmen onayından geçmelidir.

Graph retrieval şu durumlarda açılmalı:

- Birkaç bölüm arasında neden–sonuç bağlantısı
- Önkoşul bilgisi bulma
- Bir mekanizmanın farklı temsillerini birleştirme
- “DNA’dan proteine süreç nasıl ilerler?” gibi çok-adımlı sorular
- Yanlış öğrenci cevabının hangi kavram eksikliğinden kaynaklandığını bulma

Microsoft GraphRAG; entity graph, Leiden toplulukları ve topluluk özetleriyle özellikle tüm koleksiyon hakkında global sorulara odaklanır. Exact sayfa cevabı için varsayılan retrieval değildir. [Microsoft GraphRAG](https://arxiv.org/abs/2404.16130)

HippoRAG ise knowledge graph ile Personalized PageRank’i birleştirerek multi-hop retrieval’da iyi sonuçlar raporlar ve tekrarlanan LLM retrieval turlarına göre daha ucuz olabilir. [HippoRAG](https://proceedings.neurips.cc/paper_files/paper/2024/file/6ddc001d07ca4f319af96a3024f6dbd1-Paper-Conference.pdf?utm_source=chatgpt.com)

## Agentic RAG nerede kullanılmalı?

Agentic katman yalnızca şu durumlarda devreye girmeli:

- İlk retrieval’ın kanıt kapsaması yetersizse
- Soru birkaç alt soruya ayrılabiliyorsa
- Bir tabloyla açıklama metninin birleştirilmesi gerekiyorsa
- Öğrenci yanıtındaki hatanın kaynağı bulunuyorsa
- Birden fazla üniteden transfer sorusu çözülüyorsa

Agent’a verilecek sınırlar:

- En fazla 3 retrieval adımı
- Yalnızca iç kaynak araçları
- Web araması yok
- Her adımın sorgusu ve bulduğu kanıt kayıt altında
- Yeni iddia ekleyemez; yalnızca kanıt toplar
- Gerekli kanıt bulunmadığında durur
- Son üretimden sonra ayrı bir citation verifier çalışır

IRCoT, retrieval ve reasoning’i sırayla ilerletmenin multi-hop görevlerinde yararlı olabileceğini göstermiştir. [IRCoT](https://virtual2023.aclweb.org/paper_P4424.html?utm_source=chatgpt.com) Self-RAG de adaptif retrieval ve reflection tokenları kullanır; ancak bu basit bir prompt tekniği değil, özel eğitim gerektiren bir model yaklaşımıdır. [Self-RAG](https://proceedings.iclr.cc/paper_files/paper/2024/file/25f7be9694d7b32d5cc670927b8091e1-Paper-Conference.pdf?utm_source=chatgpt.com)

## Görseller, şekiller ve tablolar

Senin kitapta protein sentezi, deney şemaları, bitki yapıları, hormonlar ve taşıma dokuları gibi birçok anlam taşıyan görsel var. OCR-only sistem bunları kaybeder.

Her sayfa için iki paralel temsil tutulmalı:

1. **Metin temsili:** OCR/native text, başlık, caption, tablo hücreleri.
2. **Görsel temsili:** Tam sayfa ve önemli region crop embeddingleri.

Görsel retrieval akışı:

1. Soru ve varsa soru görüntüsü analiz edilir.
2. Text retriever ilgili kavramı arar.
3. Visual retriever ilgili sayfaları arar.
4. Sayfa üzerinde nesne/region seçilir.
5. VLM’ye yalnızca gerekli crop, caption ve yakın paragraf verilir.
6. Son cevap sayfa ve bounding box’a bağlanır.

ColPali, sayfa görüntülerini doğrudan çoklu vektörlerle indeksleyerek belge retrieval’ını OCR metnine bağımlı olmaktan çıkarır. [ColPali](https://proceedings.iclr.cc/paper_files/paper/2025/hash/99e9e141aafc314f76b0ca3dd66898b3-Abstract-Conference.html?utm_source=chatgpt.com) M3DocRAG bunu çok sayfalı ve çok belgeli VQA’ya genişletir; fakat çalışma preprint düzeyindedir. [M3DocRAG](https://arxiv.org/abs/2411.04952)

ColQwen2.5 iyi bir deney adayıdır; ancak model kartına göre retrieval eğitimi tamamen İngilizce hazırlanmış ve backbone lisansı ayrıca ticari kullanım açısından kontrol edilmelidir. Bu nedenle Türkçe üretim sistemi için doğrudan varsayılan seçmem. [ColQwen2.5 model kartı](https://huggingface.co/vidore/colqwen2.5-v0.1?utm_source=chatgpt.com)

## Model seçimi

Aşağıdaki seçimler başlangıç önerisidir. Son kazanan mutlaka senin gizli Türkçe MEB benchmarkınla belirlenmeli.

|Katman|RTX 4060 8 GB prototip|Kalite öncelikli üretim|Not|
|---|---|---|---|
|Native PDF|PyMuPDF + Docling|Parser ensemble|LLM’ye gereksiz metin çıkarımı yaptırma|
|OCR/layout|PaddleOCR + gerektiğinde Qwen3-VL-4B quantized|İki parser + güçlü VLM doğrulaması|Düşük güven bölgeleri karşılaştır|
|Dense embedding|Qwen3-Embedding-0.6B|Qwen3-Embedding-4B|8B yalnızca ölçülen kazanç maliyeti haklı çıkarırsa|
|Hibrit baseline|BM25 + BGE-M3|BM25 + Qwen3 dense + BGE-M3 sparse|Türkçe hard-negative test şart|
|Reranker|Qwen3-Reranker-0.6B|Qwen3-Reranker-4B|En iyi maliyet/kalite adayı|
|Text multi-vector|ColBERTv2 deneyi|Yalnızca ölçülen görevlerde|İndeks maliyeti daha yüksek|
|Visual retrieval|ColQwen2.5 deneysel|Lisans ve Türkçe testten sonra|Metin retrieval ile birlikte|
|Yerel VLM|Qwen3-VL-4B; 8B dar bağlam/offload ile|Qwen3-VL-8B/32B veya frontier API|Yerel model ilk taslak/ön işleme için|
|Nihai üretici|Yerel model yalnızca taslak|Model gateway üzerinden frontier model|Tek sağlayıcıya kilitlenme|
|Denetleyici|Kurallar + farklı küçük model|Bağımsız model ailesi + uzman örneklemi|Üretici kendi kendini tek başına puanlamamalı|

Qwen3 Embedding/Reranker raporu 0.6B, 4B ve 8B modelleri, 32K bağlam ve instruction-aware retrieval sunuyor. Yazarların çok dilli MTEB sonucunda embedding modelleri yaklaşık 64.33, 69.45 ve 70.58 puan alıyor; 4B’den 8B’ye fark, kaynak maliyetine göre küçük kalabilir. Fakat bunlar Türkçe MEB sonuçları değildir ve rapor preprinttir. [Qwen3 Embedding teknik raporu](https://arxiv.org/pdf/2506.05176v3?utm_source=chatgpt.com)

Üretici model için bugün kalite tavanı baseline’ında [GPT‑5.6 Sol](https://openai.com/index/gpt-5-6/?utm_source=chatgpt.com) kullanılabilir; günlük akışta Terra ayrıca denenebilir. Bağımsız challengerlara [Claude Sonnet 4.6](https://www.anthropic.com/news/claude-sonnet-4-6?utm_source=chatgpt.com) ve [Gemini 3.1 Pro Preview](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview?utm_source=chatgpt.com) eklenebilir. Bunlar sağlayıcıların kendi teknik iddialarıdır; Türkçe eğitim kanıtı sayılmazlar.

Önerim:

- Authoring ve zor soru üretimi için güçlü model
- Normal öğrenci QA için daha ekonomik model
- Görsel çıkarım için VLM
- Denetleme için farklı sağlayıcı/model ailesi
- Her üç ayda veya önemli model değişiminde kör model turnuvası

Model turnuvasında hard gate’leri geçen adaylar arasında normalize edilmiş skor kullanılabilir:

0.35 dog˘ruluk+0.25 kanıta bag˘lılık+0.15 atıf+0.10 go¨rsel+0.10 kalibrasyon+0.05 verimlilik0.35\,doğruluk+ 0.25\,kanıta\ bağlılık+ 0.15\,atıf+ 0.10\,görsel+ 0.10\,kalibrasyon+ 0.05\,verimlilik

Ancak unsupported claim sınırını geçemeyen model, toplam skoru yüksek olsa bile elenmelidir.

## Görev bazında kullanılacak sistem

### 1. Kitaptan cevap verme

Varsayılan yol:

1. Sınıf–ders–sürüm filtresi
2. BM25 + dense + sparse retrieval
3. RRF
4. Reranker
5. Parent/figure expansion
6. Kaynakla sınırlı cevap
7. Her iddia için sayfa/bbox atfı
8. Desteklenmeyen iddiayı silme veya çekimser kalma

Full-book long-context yaklaşımını ayrı baseline olarak dene; üretim sistemi yapma. 187 sayfa bir modele sığsa bile önemli bilgi ortalarda kaybolabilir ve kaynak denetimi zorlaşır.

### 2. Soru çözme

Beş ayrı deney koşulu çalıştırılmalı:

|Koşul|Ölçtüğü şey|
|---|---|
|Closed-book model|Modelin ezber/genel bilgi tabanı|
|Tüm kitap long-context|RAG’siz uzun bağlam|
|Text RAG|Metinsel retrieval|
|Multimodal RAG|Metin + sayfa görüntüsü|
|Oracle evidence|Retriever kusursuz olsaydı üreticinin başarısı|

Bu ayrıştırma çok önemlidir:

- RAG kötü, oracle iyi → retrieval sorunu.
- Oracle da kötü → reasoning/generator sorunu.
- Closed-book yüksek, yanlış kaynakla RAG düşük → model kaynağı izlemiyor.
- Görsel RAG text RAG’den iyi → visual index gerçek değer üretiyor.

Çoktan seçmeli soruda çıktı yalnızca harf olmamalı:

- Doğru seçenek
- Kanıt zinciri
- Her çeldiricinin neden yanlış olduğu
- Kaynak sayfaları
- Kalibre edilmiş güven
- Yetersiz kanıt bayrağı

Ek sağlamlık testleri:

- Seçenek sırasını değiştir
- A/B/C/D/E etiketlerini değiştir
- Soru kökünü anlamı koruyarak yeniden yaz
- Bir çeldiriciyi daha cazip hâle getir
- Görseli metinsiz ve metni görselsiz ayrı dene
- “Kesinlikle”, “olamaz”, “söylenemez” gibi nicelik/olumsuzluk kelimelerini ölç

Gönderdiğin iki protein sentezi sorusu bunun için iyi örnekler: biri nedensel zinciri, diğeri “kesin olarak söylenemez” mantığını ölçüyor. Keyword eşleşmesi tek başına yeterli olmaz.

### 3. Soru üretme

Modelden doğrudan “bu sayfadan beş soru üret” istemek kaliteli sistem değildir. Önce bir **kavram kartı** derlenmeli:

- Doğrulanmış temel iddialar
- Mekanizma veya süreç zinciri
- Gerekli ve yeterli koşullar
- Örnekler ve karşı örnekler
- Önkoşul kavramlar
- Yaygın öğrenci yanılgıları
- Görsel ve tablo temsilleri
- Kazanım
- Kaynak kanıtları

Sonra soru üretim hattı:

1. Öğretmen test blueprint’i belirler.
2. Sistem kazanım × bilişsel düzey × soru türü × zorluk hücresini seçer.
3. Kaynak kanıt paketi oluşturulur.
4. Soru gövdesi ve cevap üretilir.
5. Çeldiriciler gerçek yanılgılardan türetilir.
6. Başka bir model soruyu anahtarı görmeden çözer.
7. Ayrı critic belirsizlik, birden fazla doğru cevap ve dil hatası arar.
8. Kanıt denetleyici doğru seçeneği kaynağa bağlar.
9. Benzerlik sistemi kopya veya çok yakın soruları eler.
10. Öğretmen onaylar.
11. Öğrenci pilotundan sonra psikometrik değerler hesaplanır.

Yayınlanabilir soru şeması en azından şunları içermeli:

```
{
  "soru_id": "...",
  "sinif": 12,
  "ders": "biyoloji",
  "mufredat_surumu": "...",
  "kazanimlar": ["12.x.x.x"],
  "bilissel_duzey": "uygulama",
  "soru_metni": "...",
  "secenekler": [],
  "dogru_cevap": "C",
  "cozum": "...",
  "celdirici_gerekceleri": {},
  "kanitlar": [
    {"source_id": "...", "page": 36, "bbox": []}
  ],
  "gorsel_bagimliligi": true,
  "zorluk_hedefi": 0.55,
  "uzman_onayi": false
}
```

### 4. 187 sayfalık kitap özeti

Burada en uygun yöntem **extract-then-abstract + RAPTOR benzeri hiyerarşi**:

1. Sayfa ve bölüm düzeyinde atomik iddiaları çıkar.
2. Her iddiayı sayfa ve görsele bağla.
3. Alt başlık özeti üret.
4. Alt başlıklardan ünite özeti üret.
5. Ünite özetlerinden kitap özeti üret.
6. Kazanım–özet coverage matrisi oluştur.
7. Her özet cümlesini kaynak desteği açısından doğrula.
8. Şekil ve tabloların kaçırdığı önemli noktaları ayrı denetle.
9. Aynı kitabı %5, %10 ve %20 uzunluklarda özetle.

RAPTOR, metni özyinelemeli biçimde kümeleyip farklı soyutlama seviyelerinde özet ağacı kurar ve uzun/global sorular için güçlü bir yöntemdir. [RAPTOR](https://proceedings.iclr.cc/paper_files/paper/2024/file/8a2acd174940dbca361a6398a4f9df91-Paper-Conference.pdf?utm_source=chatgpt.com)

LongRAG ve Late Chunking de ablation kolu olabilir; fakat varsayılan yapılmadan önce Türkçe ders kitabında ölçülmelidir. [LongRAG](https://aclanthology.org/2024.emnlp-main.1259/), [Late Chunking](https://arxiv.org/abs/2409.04701)

## Katı benchmark tasarımı

### Başlangıç kapsamı

İlk vertical slice olarak 12. sınıf biyoloji çok uygun:

- Tam ders kitabı
- Konu özeti
- Çalışma defteri türü
- Görsel sorular
- 29 kazanım
- Çoktan seçmeli ve farklı soru tipleri

Fakat yalnızca burada başarılı olursa sistem “genel eğitim RAG’i” sayılmaz. İkinci dalga:

- 8. sınıf fen
- 8. sınıf matematik
- Mümkünse 8. sınıf Türkçe veya sosyal bilgiler

olmalı. Böylece bilimsel metin, şekil, matematiksel işlem ve dil ağırlıklı görevler birlikte sınanır. Sistem baştan bütün sınıfları destekleyen metadata yapısıyla kurulmalı; ama release kalitesi 8. ve 12. sınıfta kanıtlanmalı.

Önerilen ilk gizli test:

- 12. sınıf biyoloji: 1.200 sorgu
- 8. sınıf fen: 500 sorgu
- 8. sınıf matematik: 500 sorgu
- Her derste en az 50–75 tamamen layout-annotated sayfa
- Her yeni derste üretime çıkmadan önce en az 300 gizli sorgu

Sorgu dağılımı:

- %25 kesin bilgi
- %20 paraphrase
- %15 multi-hop
- %15 şekil/tablo
- %10 global/özet
- %10 cevaplanamaz
- %5 kaynak çelişkisi, yazım hatası ve adversarial örnek

### Sızıntı önleme

- Train/dev/test rastgele soru satırıyla değil, kaynak/ünite ailesiyle bölünmeli.
- Aynı sorunun görsel veya kelime değişmiş varyantları pHash, MinHash ve embedding ile tek gruba alınmalı.
- Cevap anahtarı ayrı, erişim kontrollü depoda tutulmalı.
- Soru çözme indeksinde soru sayfaları da bulunmamalı.
- Kamuya açık kitabın model eğitiminde bulunmuş olabileceği düşünülmeli.
- Gizli öğretmen materyali ve modelin dünya bilgisinin tersine kontrollü bilgi veren counterfactual testler kullanılmalı.
- Cevap anahtarları iki uzman tarafından doğrulanmalı; yayınevi anahtarı otomatik olarak mutlak doğru sayılmamalı.

### Gold benchmark kaydı

Her benchmark örneğinde:

```
soru
sınıf/ders/sürüm
görev türü
gold cevap ve kabul edilen varyantlar
bir veya daha fazla zorunlu kanıt spanı
sayfa ve bbox
yasaklı kaynaklar
görsel bağımlılığı
reasoning hop sayısı
cevaplanabilirlik
kazanım
zorluk
uzmanlar ve uyuşma durumu
```

olmalı.

## Değerlendirme metrikleri ve release kapıları

Aşağıdaki eşikler literatürde evrensel standartlar değil; senin kalite önceliğin için önerdiğim katı ürün kapılarıdır. Nokta tahmini değil, gizli setteki **%95 güven aralığının alt sınırı** eşiği geçmelidir.

|Katman|Metrik|Önerilen release kapısı|
|---|---|---|
|Native text|Character Error Rate|≤ %0,5|
|OCR sayfası|Character Error Rate|≤ %2|
|Okuma sırası|Order F1|≥ 0,98|
|Tablo|TEDS / cell F1|≥ 0,95|
|Şekil–caption|Link F1|≥ 0,98|
|ANN indeks|Exact search’e göre recall|≥ 0,995|
|Retrieval|Gold evidence Recall@20|≥ 0,98|
|Retrieval|Recall@5|≥ 0,93|
|Retrieval|nDCG@10|≥ 0,90|
|Multi-hop|Bütün gerekli kanıtların Recall@20’si|≥ 0,95|
|Görsel retrieval|Gold page Recall@10|≥ 0,95|
|Reranker|Hybrid baseline’a karşı nDCG farkı|%95 CI ile pozitif|
|Reranker|Recall@20 kaybı|≤ 0,5 puan|
|Kitap QA|Uzman doğruluğu|≥ 0,95|
|Zor visual/multi-hop|Uzman doğruluğu|≥ 0,90|
|Grounding|Claim-level faithfulness|≥ 0,99|
|Grounding|Desteksiz iddia oranı|≤ %0,5|
|Atıf|Citation precision|≥ 0,99|
|Atıf|Citation recall|≥ 0,97|
|No-answer|Yanlış cevap verme oranı|≤ %2|
|Kalibrasyon|ECE|≤ 0,05|
|Özet|Temel kazanım kapsaması|≥ 0,95|
|Özet|Kaynak destekli iddialar|≥ 0,99|
|Özet|Çelişki|0|
|QG yayın kapısı|Doğru anahtar ve kaynak desteği|%100|
|QG|Belirsiz/birden fazla doğru|≤ %1|
|QG|İlk öğretmen kabulü|≥ %85|
|Güvenlik|Yasaklı answer-key retrieval|0 olay|

Retrieval/generator hatalarını ayrıştırmak için RAGChecker’ın claim-level metrikleri faydalıdır: retriever claim recall, context precision, faithfulness, gürültü hassasiyeti, hallucination ve context utilization. [RAGChecker](https://arxiv.org/abs/2408.08067)

ARES, otomatik judge’ları yaklaşık 150 veya daha fazla insan etiketiyle kalibre edip güven aralıkları üretme yaklaşımı sunar. [ARES](https://aclanthology.org/2024.naacl-long.20/) RAGAS hızlı geliştirme metriği olarak kullanılabilir ama tek release kapısı olmamalıdır. [RAGAS](https://aclanthology.org/2024.eacl-demo.16/) RAGTruth ise hallucination denetleyicisi eğitmek için word-level etiketli geniş bir kaynak sunar. [RAGTruth](https://aclanthology.org/2024.acl-long.585/?utm_source=chatgpt.com)

### Özet değerlendirmesi

ROUGE veya BERTScore tek başına kullanılmamalı. Ölçülmesi gerekenler:

- Uzman tanımlı temel iddia coverage’ı
- FActScore benzeri atomik olgu desteği
- Faithfulness
- Completeness
- Conciseness
- Citation precision/recall
- Şekil/tablo bilgi coverage’ı
- Özetten cevaplanabilen kaynak-temelli soru oranı

Kaynaklar: [SummHay](https://arxiv.org/abs/2407.01370), [FActScore](https://aclanthology.org/2023.emnlp-main.741/), [FineSurE](https://aclanthology.org/2024.acl-long.51/). LCFO çalışmasının otomatik özet metrikleri ile insan değerlendirmesi arasındaki korelasyonu düşük bulması, uzman denetiminin zorunlu olduğunu destekliyor. [LCFO](https://aclanthology.org/2025.findings-acl.556/?utm_source=chatgpt.com)

### Soru üretimi psikometrisi

Öğrenci pilotundan sonra:

- Madde güçlüğü pp
- Point-biserial ayırt edicilik: en az 0,25; tercihen 0,30+
- Çeldirici seçilme oranları
- Hiç çalışmayan çeldirici oranı
- Güvenirlik
- IRT 2PL/3PL parametreleri
- Sınıf, cinsiyet veya okul türüne göre DIF
- Süre
- Kazanım coverage’ı
- AI’sız transfer başarısı

hesaplanmalı. Klasik madde analizi için madde başına yaklaşık 200 yanıt başlangıç olabilir; kararlı IRT ve DIF için 500+ yanıt tercih edilir. Çalışmayan ve yanlılık şüphesi taşıyan madde uzman incelemesi olmadan yayınlanmamalı.

## Zorunlu ablation deneyleri

|Deney|Neyi gösterir?|
|---|---|
|BM25|Sözcüksel taban çizgisi|
|Dense-only|Anlamsal retrieval katkısı|
|BM25 + dense RRF|Hibrit katkı|
|Hibrit + reranker|Reranking katkısı|
|+ proposition/parent chunk|Chunk mimarisi katkısı|
|+ visual index|Şekil/tablo katkısı|
|+ curriculum graph|Multi-hop ve yönlendirme katkısı|
|+ RAPTOR|Global özet katkısı|
|+ bounded agent|Çok-adımlı retrieval katkısı|

Her bileşen için:

- Kalite
- p50/p95 latency
- Maliyet
- Token miktarı
- Retrieval hatası
- Generator hatası
- Sınıf/ders bazlı regresyon

raporlanmalı. “Daha gelişmiş göründüğü” için hiçbir bileşen tutulmamalı. Yalnızca hedef görev diliminde istatistiksel ve pratik kazanç üreten bileşen üretime alınmalı.

## Fine-tuning sırası

Başlangıçta generator fine-tune etmeni önermiyorum. Sıra şöyle olmalı:

1. Zero-shot BM25 + Qwen/BGE baseline
2. Gold Türkçe query–evidence seti
3. Hard-negative mining
4. Reranker LoRA/fine-tuning
5. Gerekirse embedding fine-tuning
6. Yeterli Türkçe query–page çifti oluşursa visual retriever adaptation
7. En son, öğretmen onaylı veri yeterliyse generator fine-tuning

Hard negative örnekleri:

- Aynı terim, yanlış sınıf
- Aynı kavram, yanlış biyolojik süreç
- Yakın başlık fakat soruya cevap vermeyen paragraf
- Doğru cevaba benzeyen çeldirici açıklaması
- Yanlış müfredat sürümü
- Soru/cevap anahtarı sayfası
- Aynı görünümlü fakat farklı eksenli grafik

Reasoning-intensive retrieval’ın hâlâ çözülmemiş olduğunu gösteren BRIGHT benchmarkı nedeniyle genel benchmark sonuçlarıyla yetinmemek gerekir. [BRIGHT](https://proceedings.iclr.cc/paper_files/paper/2025/hash/7a0f8055c838df8e62329a76c7c6403d-Abstract-Conference.html?utm_source=chatgpt.com)

## Uygulama sırası

1. **12. sınıf biyoloji corpus compiler**
    - 187 sayfanın layout ayrıştırılması
    - Cevap anahtarı ve soru bölgelerinin izolasyonu
    - 29 kazanımın graph omurgasına eklenmesi
    - Sayfa/bbox citation sistemi
2. **Text RAG baseline**
    - BM25
    - Qwen3-Embedding-0.6B ve BGE-M3
    - Qwen3-Reranker-0.6B
    - 1.200 soruluk gizli retrieval/QA seti
3. **Multimodal katman**
    - Görsel sayfa ve crop indeksi
    - Şekil/tablo benchmarkı
    - ColQwen ailesi ile text+visual fusion ablationı
4. **Soru çözme ve üretme**
    - Eksik 434 görsel ve bütün soru gövdelerinin alınması
    - Soru–kazanım eşlemesi
    - Çözüm kanıtları
    - Teacher review ve psychometric pilot
5. **RAPTOR kitap özeti**
    - Alt başlık, ünite ve kitap düzeyi
    - %5/%10/%20 özetler
    - Coverage ve citation benchmarkı
6. **8. sınıf transfer testi**
    - Önce fen ve matematik
    - Ardından dil/sosyal ders
    - Aynı modellerin grade drift ve domain drift analizi
7. **Graph/agent ekleme**
    - Yalnızca text+visual hybrid baseline’ın çözemediği multi-hop örneklerde
    - Ablation kazancı kanıtlanırsa

## Son hükmüm

Senin sistemin için çekirdek çözüm:

> **BM25 + Qwen3 dense embedding + neural sparse retrieval + Qwen3 reranker + sayfa görüntüsü retrieval + curriculum graph + RAPTOR; üstünde sınırlı bir adaptive router ve claim-level verifier.**

Başlangıç modeli:

- Yerel prototip: Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B + BM25
- Üretim retrieval: Qwen3 4B modelleri ve BGE-M3 karşılaştırması
- Görsel: ColPali/ColQwen deney kolu + Qwen3-VL doğrulaması
- Kalite tavanı generator: GPT‑5.6 Sol başlangıç baseline’ı
- Bağımsız kontrol: farklı model ailesi + öğretmen örneklemi
- Global kitap özeti: RAPTOR
- GraphRAG: yalnızca global veya multi-hop görev
- Agentic RAG: yalnızca kanıt yetersizliğinde, en fazla 2–3 tur
- Release ölçütü: ortalama skor değil; her kritik alt görevde güven aralıklı hard gate

Bu yaklaşım, kullanıcıya sadece “PDF üzerinde konuşan chatbot” değil, her cevabı sayfa ve görsel kanıtına bağlanan, kazanım kontrollü ve ciddi biçimde test edilmiş bir **AI ders derleyicisi** verir.

İstersen, “Aylık RAG literatür güncellemesi” kurulabilir; yeni retrieval, reranker ve multimodal benchmarklar geldikçe model kararlarını güncel tutar.