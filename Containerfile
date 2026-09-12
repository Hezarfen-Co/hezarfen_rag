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

# Konteynerde CPU torch (yerel geliştirmede GPU/cu130 kullanılır; GPU
# passthrough ayrı kurulum ister). TIRNAK ŞART — bkz. yukarıdaki OPS-17 notu.
COPY requirements.txt .
RUN pip install --no-cache-dir "torch>=2.6" --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt \
 && test ! -e /app/=2.6      # yönlendirme çöpü oluşmadığını DOĞRULA

COPY src ./src

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
CMD ["python", "-m", "uvicorn", "src.service.http_app:create_app_with_warmup", \
     "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-graceful-shutdown", "20"]
