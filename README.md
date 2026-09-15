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

`.env` içindeki `DEEPSEEK_API_KEY` değerini doldurun. Gerçek `.env` GitHub'da
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

`compose.yaml` iki profil sunar. Fark yalnız hız değil: **kapı O-05 (p50 ≤ 6 s)
CPU'da geçilemiyor.**

| profil | torch | ölçülen p50 | kapı O-05 |
|---|---|---|---|
| `product` (CPU) | cu yok | ~96 s | ✗ |
| `gpu` | cu130 | **4,96 s** | ✓ |

*(RTX 4060 Laptop, 10/biyoloji, gerçek `/rag/chat`, 10 soru — bkz. EXP-018.)*

```bash
podman compose --profile product up -d --build     # CPU
podman compose --profile gpu     up -d --build     # GPU
```

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

Gömme ve rerank ayrı ayrı seçilebilir. **Varsayılan `local`**: ölçülmüş bütün
kalite sayıları (EXP-011/013/017/018) o yola aittir.

```bash
RAG_EMBED_PROVIDER=local    # local | api
RAG_RERANK_PROVIDER=local   # local | api | off
```

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

Bunlar sessizce yaşanmaz; kod açılışta uyarır ya da durdurur.

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
