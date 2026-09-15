# hezarfen_rag — RAG servisi konteyneri (Podman; Docker DEĞİL)
#
# #81 (EXP-010/OPS-03 + OPS-17) — ÖNCEKİ HÂLİN SORUNLARI:
#   * `CMD ["python","-c","import src; print('...hazir...')"]` → imge bir metin
#     yazdırıp ÇIKIYORDU; `uvicorn` hiç çalıştırılmıyordu. `restart:
#     unless-stopped` ile birlikte bu SONSUZ RESTART DÖNGÜSÜ demekti.
#   * `RUN pip install torch>=2.6 --index-url ...` → tırnaksız `>=` KABUK
#     YÖNLENDİRMESİNE dönüşüyordu: sürüm kısıtı hiç uygulanmıyor, `/app/=2.6`
#     çöp dosyası oluşuyor, pip çıktısı build loglarında görünmüyordu.
#   * `EXPOSE` yok, compose'da `ports` ve `healthcheck` yok.
#   * `.containerignore` `data/`'yı dışlıyor ama `BOOK_PATH` varsayılanı
#     `data/...` → PDF konteynerde HİÇ YOK. Artık volume ile bağlanır.
FROM docker.io/library/python:3.11-slim

WORKDIR /app

# `curl` sağlık yoklaması için (distroless değil; bilinçli tercih: healthcheck
# imge içinden çalışabilsin).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# #96 (EXP-018) — TORCH DEĞİŞKENİ SEÇİLEBİLİR.
#
# Önceki hâl CPU torch'u SABİT kuruyordu. Ölçüldü (RTX 4060, 10/biyoloji,
# gerçek /rag/chat):
#
#            | rerank (40 aday) | uçtan uca p50
#   CPU      |      95,9 s      |     96 s
#   GPU      |       1,9 s      |   **4,96 s**
#
# Kapı O-05 p50 <= 6 s istiyor: CPU'da GEÇİLEMEZ, GPU'da GEÇİLİYOR. Yani imgeyi
# CPU torch'a sabitlemek, ürünü okul demosunda interaktif OLMAYAN tek
# yapılandırmaya kilitlemek demekti.
#
# VARSAYILAN CPU KALDI — GPU imgesi ~2,5 GB daha büyük ve çalışması için ana
# makinede NVIDIA Container Toolkit ŞART (bkz. compose.yaml). GPU'suz bir
# makinede cu130 tekerleği kurmak yalnız yer kaplar.
#
#   CPU (varsayılan):
#     podman build -t hezarfen-rag:cpu .
#   GPU:
#     podman build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu130 \
#                  -t hezarfen-rag:gpu .
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

# TIRNAK ŞART — bkz. yukarıdaki OPS-17 notu.
COPY requirements.txt .
RUN pip install --no-cache-dir "torch>=2.6" --index-url "${TORCH_INDEX}" \
 && pip install --no-cache-dir -r requirements.txt \
 && test ! -e /app/=2.6      # yönlendirme çöpü oluşmadığını DOĞRULA \
 && python -c "import torch, sys; \
print('torch', torch.__version__, 'cuda-build:', torch.version.cuda); \
sys.exit(0)"

COPY src ./src

# Dağıtım varsayılanları — TEK yazıldıkları yer. Sunucu bunları
# hezarfen_rag.env (env_file) ile ezer.
# (Korpus seçimi — BOOK_PATH/SINIF/DERS — compose.yaml'da interpolasyon
# varsayılanı olarak durur: cihaza özel oldukları için dağıtım dosyasından
# gelirler.)
ENV HF_HOME=/models \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# Ayrıcalıksız kullanıcı: model cache ve veri volume'ları bu kullanıcıya ait olur.
RUN useradd --create-home --uid 10001 hezarfen \
 && mkdir -p /models \
 && chown -R hezarfen:hezarfen /app /models
USER hezarfen

# Sunucu ÖNCE ayağa kalkar, boru hattı arka planda kurulur (#82) → sağlık
# yoklaması ilk saniyeden itibaren cevap verir.
#
# Fabrika (`--factory`) şart: modül seviyesinde `app = ...` her içe aktarmada
# ısıtma thread'i başlatırdı (tests/unit/test_deployment.EntrypointTests).
# Adres/port ORTAMDAN gelir (yukarıdaki ENV bloğu = varsayılanların tek
# kaynağı, hezarfen_rag.env = operatörün ezmesi): sabit `--host 0.0.0.0 --port
# 8000` yazmak, ortamdan gelen PORT'u yok sayardı — daha önce aynı sayı üç
# yerde (ENV, app main(), CMD) tutuluyordu.
CMD ["sh", "-c", "exec python -m uvicorn src.service.http_app:create_app_with_warmup --factory --host \"$HOST\" --port \"$PORT\" --timeout-graceful-shutdown \"${RAG_GRACEFUL_SHUTDOWN_S:-20}\""]
