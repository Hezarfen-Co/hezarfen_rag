# hezarfen_rag

## Yeni bilgisayarda geri yükleme (PowerShell)

Bu özel depo `data/`, `models/`, `eba_dl/` ve `mockdata/` içerir.
Veri ve modeller Git LFS ile saklanır. ZIP indirmek yerine Git LFS ile klonlayın.

```powershell
git lfs install
git clone https://github.com/Hezarfen-Co/hezarfen_rag.git
cd hezarfen_rag
git lfs pull
git lfs fsck
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` içindeki `LLM_API_KEY` değerini doldurun (tek LLM anahtar adı;
eski `DEEPSEEK_API_KEY`/`NVIDIA_API_KEY` adları kaldırıldı — varsa servis reddeder). Gerçek `.env` GitHub'da
bulunmaz: bilgisayarı sıfırlamadan önce anahtarı parola yöneticisine veya güvenli
harici yedeğe kaydedin. Diğer servislerin sırları ve veritabanları bu RAG deposunun
yedeğine dahil değildir.

HTTP servisi `.env` dosyasını otomatik yüklemez. Başlatmadan önce değişkenleri yükleyin:

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}
.\.venv\Scripts\python.exe -m src.service.http_app
```

OCR gerekiyorsa Tesseract kurun; `TESSERACT_CMD` yolunu makinenize göre ayarlayın.
Türkçe dil modeli `models/tessdata/tur.traineddata` altında LFS ile saklanır.
Embedding/reranker modelleri ilk çalıştırmada internetten indirilir.
GPU kurulumu için `requirements.txt` içindeki PyTorch yönergelerini izleyin.
`.venv`, Python önbellekleri ve pytest önbelleği yeniden oluşturulur.
Konteyner dağıtımı için aşağıdaki **Linux / Podman** bölümüne bakın (`compose.yaml`
artık gerçekten servisi başlatır — eski "yalnız hazırlık kontrolü" notu #81 ile
geçersizleşti).

Veri dosyalarının SHA-256 doğrulaması: python verify_backup.py (15,6 GB okur).
Yedek mevcut dosyaları aynen korur; data içindeki üç .part dosyası tamamlanmamış indirmelerdir.


## Linux / Podman — konteyner dağıtımı

`compose.yaml` iki profil sunar. Ölçülen tablo **yerel modellerle** alındı ve
dağıtım varsayılanının neden `api` olduğunu gösterir: kapı O-05 (p50 ≤ 6 s)
yerel modellerle CPU'da geçilemiyor.

| profil | torch | sağlayıcı | ölçülen p50 | kapı O-05 |
|---|---|---|---|---|
| `product` (CPU) | cu yok | **api** (dağıtım varsayılanı): rerank uzakta | — | ✓ (rerank 95,9 s'lik adım kalkar) |
| `product` (CPU) | cu yok | `local`: rerank bu makinede | ~96 s | ✗ |
| `gpu` | cu130 | `local` | **4,96 s** | ✓ |

*(RTX 4060 Laptop, 10/biyoloji, gerçek `/rag/chat`, 10 soru — bkz. EXP-018.)*

```bash
podman compose --profile product up -d --build     # CPU
podman compose --profile gpu     up -d --build     # GPU
```

Dağıtım varsayılanlarının **tek kaynağı** `Containerfile`'ın `ENV` bloğudur
(HF_HOME, HOST, PORT ve **sağlayıcı seçimi**: `RAG_EMBED_PROVIDER=api`,
`RAG_RERANK_PROVIDER=api`). `compose.yaml`'ın `environment:` bloğu yalnız
cihaza özel korpus seçimini (BOOK_PATH/SINIF/DERS, interpolasyon varsayılanlı)
taşır; operatöre ait her şey `~/hezarfen_rag/hezarfen_rag.env` dosyasından
gelir (şablon: **`deploy/hezarfen_rag.env.example`**, `env_file:` ile okunur,
dosyayı otomatik hiçbir şey yazmaz). Değerler konteyner **başlarken** okunur:
değişiklikten sonra yeniden oluştur, yoksa eski değerlerle çalışmaya devam eder.

**Eksik sağlayıcı yapılandırması sessizce geçilmez.** Seçilen sağlayıcının
taban adresi/modeli/anahtarı yoksa servis **açılışta reddeder**
(`src/service/preflight.py`) — uvicorn portu dinlemeden süreç çıkar, `/health`
hiç `ok` demez, deploy kapısı rollback yapar. Elle denetim:

```bash
python -m src.service.preflight          # ya da: python -m src.service.http_app --validate
```

Neden bu kapı var: eksik anahtarla ayakta kalan servis `/health` ve `/ready`'de
yeşil kalıyor, yalnız **ilk gerçek soru** düşüyordu — deploy kapısı geçer, ürün
ölü olur. Ön denetim eksiği ADIYLA söyler (hangi değişkene ne yazılacağı).

**Kaynak zarfı — tek kaynak `compose.yaml` → `x-rag-envelope`:** konteyner
`mem_limit` **3072 MB**, disk eşiği **8 GB** (rollback iki imajı da tutar).
Ölçüm (API sağlayıcı yolu; PROJECT_STATE §11.2): torch import ~0,4 GB +
0,53 GB/10k chunk → tek korpus ≈1,1 GB, 3×10k chunk ≈2,6 GB. CI kapasite
kapısı bu iki sayıyı compose'dan okur (koda ikinci kez yazılmaz).

### CI deploy (GitHub Actions)

`.github/workflows/main.yml` kardeş servislerle aynı şekli taşır: `Validate`
(derleme kontrolü) ∥ `Build and test` (`python -m pytest tests/unit -q` süiti +
imaj + `release` artefaktı) → `Deploy` (SSH: imajı yükle, deploy sahipli
`stack.env`'in
`HEZARFEN_TAG`'ini çevir, unit'i kur, `/health` ve `/ready` kapılarını geçir,
geçmezse önceki tag'e dön). Unit'in kendisi sürümle birlikte iner:
`deploy/hezarfen_rag_compose.service`.

**Deploy yalnız elle koşar** (`workflow_dispatch`) ve kapıda **kapasite ön
kontrolü** vardır: eşikler `compose.yaml`'daki `x-rag-envelope` bloğundan
okunur — RAM ≥ `mem_limit_mb` (**3072 MB**) ve disk ≥ **8 GB**; yetmezse
nedeniyle birlikte reddeder. Gerekçe ölçülmüş: API gömme + API rerank ile
yerel modeller hiç indirilmez (zarf 1,1–2,6 GB), yani eski 12 GB / 20 GB
eşikleri model çağından kalmaydı. Ölçtüğümüz 7 GB'lık geliştirme sunucusu
(6 466 MB boşta) bu kapıdan artık **geçer**.

Kapıyı açmak için: repo secret'larına `SSH_PRIVATE_KEY`/`SSH_HOST`/`SSH_USER`
ekle, sunucuya `~/hezarfen_rag/hezarfen_rag.env` (0600, şablon:
`deploy/hezarfen_rag.env.example`) ve `~/hezarfen_rag/data/`
(`<okul>/lise/<sınıf>/<ders>/kitap.pdf`) korpusunu koy, sonra
`workflow_dispatch` ile koş.

### GPU için tek seferlik ana makine kurulumu

Kap GPU'yu ancak **NVIDIA Container Toolkit** kuruluysa görür. Kurulu değilse
torch **sessizce CPU'ya düşer**: servis sağlıklı görünür, her soruya bir buçuk
dakikada cevap verir ve log'da tek satır uyarı olmaz.

Fedora (root gerekir — bir kez, bütün projeler için):

```bash
curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo \
  | sudo tee /etc/yum.repos.d/nvidia-container-toolkit.repo
sudo dnf install -y nvidia-container-toolkit
sudo mkdir -p /etc/cdi
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
sudo setsebool -P container_use_devices 1
```

Son satır **Fedora'da şart** ve atlanması kolay: SELinux `Enforcing` iken
`container_use_devices` varsayılan olarak **kapalıdır**. CDI tanımı doğru
üretilmiş olsa bile kap `/dev/nvidia*`'ya erişemez ve şu hatayı verir:

```
Failed to initialize NVML: Insufficient Permissions
```

Bu hata "GPU yok" demez — CDI çözülmüştür, sürücü yerindedir, yalnız SELinux
engellemektedir. Teşhis: `getenforce` → `Enforcing`,
`getsebool container_use_devices` → `off`.

> `--security-opt=label=disable` ile de çalışır ama o, kabın SELinux
> etiketlemesini **tamamen** kapatır (dosya sistemi koruması dahil). Boolean
> yalnız aygıt erişimini açar; kabın geri kalan kısıtları yerinde kalır.

`nvidia-ctk cdi generate` çıktısındaki `Could not locate ...` uyarıları
(`nvidia_drv.so`, `vulkan/icd.d/...`, `nvidia-imex`) **beklenen**: bunlar X11 /
Vulkan / çok-düğümlü bileşenler, hesaplama için gerekmez. Önemli satırlar
`Selecting /usr/lib64/libcuda.so...` ve `Generated CDI spec`.

Doğrulama (kap `nvidia-smi`'yi görmeli):

```bash
podman run --rm --device nvidia.com/gpu=all \
  docker.io/library/python:3.11-slim nvidia-smi
```

> Sürücü güncellendiğinde `nvidia-ctk cdi generate` **tekrar çalıştırılmalıdır**;
> CDI tanımı sürücü dosyalarının yollarını sabitler.

### Sessiz CPU'ya düşüşe karşı koruma

`gpu` profili `RAG_REQUIRE_CUDA=1` ile gelir: CUDA görünmüyorsa servis
**açılışta hata verir** ve üç olası nedeni de söyler (imge CPU torch ile mi
kuruldu, toolkit kurulu mu, `--device` verildi mi). 96 s'lik "çalışan" bir
servis, çalışmayan bir servisten daha kötüdür.

CUDA durumu `/ready` uçtan da okunabilir:

```bash
curl -s http://127.0.0.1:8000/ready | python -m json.tool
# {"status": "ready", ..., "cuda": {"available": true, "device_name": "NVIDIA GeForce RTX 4060 ..."}}
```

### Bilinen sınır — eşzamanlılık

Gecikme eşzamanlı istekle neredeyse doğrusal büyüyor (embed ve rerank tek GPU'da
sıraya giriyor):

| eşzamanlı öğrenci | 1 | 3 | 5 | 8 |
|---|---|---|---|---|
| p50 | 4,96 s | 6,08 s | 9,31 s | 11,54 s |

Öğretmenin tek ekrandan gösterdiği demo sorunsuz; "herkes kendi cihazından aynı
anda sorsun" senaryosu bu hâliyle kapıyı geçmez (#96 / O-06).


## Sağlayıcı seçimi — yerel model ↔ uzak API

Gömme ve rerank ayrı ayrı seçilebilir ve **ikisi de tam çalışır durumda**.

| | `RAG_EMBED_PROVIDER` | `RAG_RERANK_PROVIDER` | kime |
|---|---|---|---|
| **Dağıtım varsayılanı** | `api` | `api` | 7,6 GiB'lik GPU'suz sunucu; ölçülen zarf 1,1–2,6 GB |
| **Sahadaki dağıtım seçimi (2026-09-17)** | `voyage` | `api` | Voyage'ın ücretsiz kotası: `voyage-multilingual-2` (1024 boyut) + `rerank-3` |
| Yedek API yolu | `cohere` | `api` | Cohere native `/v2/embed`; `input_type` uyumluluk katmanında reddediliyor |
| Ölçülmüş kalite yolu | `local` | `local` | golden set / eval; bütün kalite sayıları (EXP-011/013/017/018) buraya ait |

**Ücretsiz kota iddiası BELGELENMİŞTİR, ÖLÇÜLMEMİŞTİR:** Voyage'ın
fiyatlandırma sayfası hangi modellerin ücretsiz kotayı taşıdığı konusunda kendi
içinde tutarsızdır. Doğrulama yeri sağlayıcı panelinin kullanım/faturalama
ekranıdır (belgelenen: `voyage-multilingual-2` 50M token, `rerank-3` 200M işlenen
token). Ücret sürprizi istemiyorsan ilk gerçek indeksten sonra oraya bak.

### Sağlayıcıların birbirinden AYRILDIĞI iki nokta (ikisi de ölçüldü)

| | istek gövdesi | `input_type` | rerank yanıtı | rerank sınır alanı |
|---|---|---|---|---|
| `api` (OpenAI-uyumlu) | `input[]` + `/embeddings` | sorgu/pasaj AYNEN gider | `results[]` | `top_n` |
| `voyage` | `input[]` + `/embeddings` | `query` / **`document`** | **`data[]`** | **`top_k`** |
| `cohere` | `texts[]` + `/embed` | `search_query` / `search_document` | `results[]` | `top_n` |

Yanlış olanı göndermek sessiz bir kalite kaybı değil, AÇIK bir 4xx'tir — bu
yüzden bu tablo kodda sabittir: Voyage `passage` → 400 "accepted values are
'query' or 'document'"; Cohere `top_k` → 422 "unknown field"; Voyage `top_n` →
400 "Argument 'top_n' is not supported". Sınır alanının adı uç adından çözülür
(`RAG_RERANK_TOP_K_PARAM` ile ezilebilir).

**BOYUT DEĞİŞMEZİ:** indeks 1024 boyutludur (BGE-M3 dense). Modeli 384'lük
`light` varyantına çevirmek vektörleri karıştırırdı; ilk gömme — hiçbir sorgu
koşmadan — `EmbeddingDimensionMismatch` ile, model ADI ve İKİ boyutla
reddedilir (`src/embed/provider.py::_BoyutKapisi`). Boyut değiştirmek korpusun
tamamının yeniden indekslenmesini gerektirir.

Yerel yol **silinmedi** ama artık **imajda değil**: varsayılan imge KÜÇÜKTÜR
(torch/FlagEmbedding/ağırlık YOK). Yerel bağımlılıklar bir podman **volume'ü**
içindeki venv'de durur; servis onu `sys.path`e ekler. Geçiş **workflow'suz ve
derlemesizdir**:

```bash
# 1) volume'u BİR KEZ sağla (pip İMGE İÇİNDE koşar: ABI/glibc uyumu şart).
#    İdempotent: tekrar koşmak günceller, ikizlemez. --agirliklari-indir ~4,5 GB
#    ağırlığı şimdi indirir (yoksa ilk yerel istekte iner).
bash deploy/provision_local_stack.sh

# 2) ~/hezarfen_rag/hezarfen_rag.env (satır-içi `#` yorum KOYMA)
RAG_EMBED_PROVIDER=local
RAG_RERANK_PROVIDER=local
RAG_LOCAL_VENV=/local-stack/venv
RAG_LOCAL_MODELS_DIR=/models

# 3) uygula — başka hiçbir şey
systemctl --user restart hezarfen_rag_compose
```

Volume mount'u `compose.yaml`'da **hep takılıdır** (boş volume zararsız), yani
geçiş yalnız `.env` + restart'tır. Sağlanmamış volume ile `local` seçilirse
servis **açılışta, adıyla ve komutuyla** reddeder (ImportError değil):
`RAG_LOCAL_VENV` + `provision_local_stack.sh` mesajda geçer. `/ready` de
`saglayici.yerel_yigin` alanında "yok" / "provisioned … tag=… python=…" bildirir.

**DİKKAT — RAM (dürüst uyarı):** yerel modda BGE-M3 + reranker ~4,5 GB ister ve
7,6 GiB'lik sunucu bunu backend+postgres+frontend+chatbot ile PAYLAŞIR. Yani
yerel mod bu kutuda "diğer servisleri kapat" modudur; API modu (varsayılan) 1,1–2,6 GB.

### Neden API seçeneği var

Sorgu başına gecikme CPU'da parçalara ayrıldı (EXP-018):

| parça | CPU |
|---|---|
| sorgu embed | 0,122 s |
| hibrit arama | milisaniye |
| **rerank (40 aday)** | **95,9 s** |
| LLM (DeepSeek, zaten uzak) | ~2–3 s |

GPU'yu isteyen **tek** parça rerank. Uzak servise taşınırsa CPU yeter.

### API'ye geçmenin ölçülmüş bedelleri

Bunlar sessizce yaşanmaz; kod açılışta uyarır ya da durdurur. **API yolu artık
dağıtım varsayılanıdır** (`Containerfile` ENV) — yani aşağıdaki bedeller
üretimde geçerlidir; yerel yola dönüş iki satırdır (yukarıda).

1. **Sparse vektör kaybolur.** BGE-M3 dense + sparse'ı tek geçişte üretir;
   hibrit retrieval üç ayağa dayanır (dense + BM25 + sparse). OpenAI-uyumlu
   `/v1/embeddings` uçları **yalnız dense** döndürür. BM25 kalır, sparse gider.
2. **Ölçülmüş kalite sayıları geçersizleşir.** Başka gömme modeli = başka
   vektör uzayı. Golden set yeniden koşulmalı.
3. **İndeks geçersizleşir.** Farklı boyut/uzay; `corpus_version` değişmeli.
4. **Çekimserlik kapısı anlamsızlaşır.** `abstain_score=0,30` eşiği yerel BGE
   reranker'ın sigmoid dağılımı üzerinde ölçüldü (EXP-017). Başka sağlayıcıda
   kapı **hiç tetiklenmez** ve ürün kitapta olmayan soruya da cevap üretmeye
   çalışır. Servis bu durumda **açılışta hata verir**; geçmek için eşiği
   yeniden kalibre et (`python -m src.eval.calibrate_abstain_cli`),
   `RAG_ABSTAIN_SCORE=0` ile kapıyı bilerek kapat, ya da riski kabul et
   (`RAG_ALLOW_UNCALIBRATED_ABSTAIN=1`).

### `off` hakkında

`RAG_RERANK_PROVIDER=off` aday sırasını (RRF) korur ve en ucuz seçenektir ama
**ölçümle desteklenmiş değildir**. EXP-018'de RRF reranker'ı geçmiş görünüyor
(r@6 0,939 vs 0,890) — ancak o ölçüm reranker'ın aleyhine kuruludur: 66
item'ın 55'inde sorgu, birimin *kendi metnidir* (iğne testi), soru değil. Tek
soru biçimli kategoride reranker öndeydi. Bu set "reranker gereksiz" sonucunu
**veremez** (#91).


## Çok dersli kurulum (#86)

Varsayılan olarak servis **tek kitap** okur (`BOOK_PATH`). `RAG_CORPORA`
verilirse birden çok derse cevap verir; sohbette ders `options.ders` ile
seçilir (API-CONTRACT).

```bash
RAG_CORPORA=10/biyoloji,10/kimya,10/cografya   # ya da: all
RAG_WARM_CORPORA=all                            # demo öncesi ısıtma (ops.)
```

**Ölçüldü** (RTX 4060, gerçek `/rag/chat`):

| | süre | sonuç |
|---|---|---|
| soğuk dersin 1. sorusu | 0,00 s | `service_warming_up` — kurulum arkada başlar |
| 10/biyoloji kurulumu | 55,0 s | 327 chunk |
| 10/kimya kurulumu | 171,5 s | 438 chunk |
| biyoloji sorusu | 9,83 s | 2 atıf (s. 99, 102) |
| kimya sorusu | 4,27 s | 2 atıf (s. 20, 43) |

Üç davranış bilinçlidir:

- **Korpuslar tembel kurulur.** 15 kitabı açılışta kurmak ~12 dakikalık sağır
  servis demekti ve indeks kalıcı olmadığı için (#75) bu bedel her yeniden
  başlatmada ödenirdi. Demo öncesi `RAG_WARM_CORPORA=all` ile ısıtın.
- **Kurulumlar seridir.** İki korpus paralel kurulunca süreç segfault ile
  çöküyordu (paylaşılan BGE-M3 örneğini iki thread'den eş zamanlı kullanmak).
  Sorgular bu kilitten etkilenmez.
- **Çok dersli rol + ders seçilmemişse ürün tahmin etmez**, `corpus_ambiguous`
  der. Tahmin etmek yanlış kitaptan cevap üretmek olurdu.

`/ready` hangi derslerin hazır, kurulmakta ya da hatalı olduğunu raporlar.
