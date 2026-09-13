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
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```

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
