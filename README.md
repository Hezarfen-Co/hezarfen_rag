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
Mevcut `compose.yaml` yalnızca hazırlık kontrolü çalıştırır; HTTP servisini yukarıdaki
komutla başlatın. Tam yeni-makine/GPU kurulumu bu yedekleme sırasında sınanmadı.

Veri dosyalarının SHA-256 doğrulaması: python verify_backup.py (15,6 GB okur).
Yedek mevcut dosyaları aynen korur; data içindeki üç .part dosyası tamamlanmamış indirmelerdir.
