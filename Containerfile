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

# KÜÇÜK VARSAYILAN İMGE (kullanıcı kararı 2026-09-17): yerel model yığını
# (torch + FlagEmbedding + ağırlıklar) İMAJA HİÇ GİRMEZ. Varsayılan imge yalnız
# servis yolunu taşır ve API sağlayıcılarıyla çalışır.
#
# YEREL YOL SİLİNMEDİ — EKLENTİ VOLUME OLARAK TAKILIR (imgeyi yeniden derlemeden
# .env'den seçilir):
#   * yerel bağımlılıklar volume İÇİNDEKİ bir venv'de yaşar (RAG_LOCAL_VENV)
#   * ağırlıklar aynı/sibling volume'da (RAG_LOCAL_MODELS_DIR → HF_HOME)
#   * sağlama (tek komut, idempotent): deploy/provision_local_stack.sh
#   * seçim: RAG_EMBED_PROVIDER=local + RAG_RERANK_PROVIDER=local, sonra
#     `systemctl --user restart hezarfen_rag_compose` — workflow YOK, derleme YOK.
# Sağlanmamış volume ile `local` seçilirse servis AÇILIŞTA reddeder
# (src/service/preflight.py) — ImportError traceback'i değil, adı söylenen hata.
#
# Yerel yetenekli imge isteyen (eski davranış) için build arg KALDIRILMADI:
#   podman build --build-arg WITH_LOCAL_MODELS=1 [--build-arg TORCH_INDEX=...] .
# (VPS'te önerilen yol volume'dur: imge CI'dan gelir, yeniden derleme gerekmez.)
ARG WITH_LOCAL_MODELS=0
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

# TIRNAK ŞART — bkz. yukarıdaki OPS-17 notu.
COPY requirements.txt requirements-local.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && if [ "$WITH_LOCAL_MODELS" = "1" ]; then \
      pip install --no-cache-dir "torch>=2.6" --index-url "${TORCH_INDEX}" \
      && pip install --no-cache-dir -r requirements-local.txt; \
    fi \
 && test ! -e /app/=2.6      # yönlendirme çöpü oluşmadığını DOĞRULA \
 && python -c "import sys; \
try: \
    import torch; print('torch', torch.__version__, 'cuda-build:', torch.version.cuda); \
except ModuleNotFoundError: \
    print('torch YOK — kucuk imge (API saglayici yolu)'); \
sys.exit(0)"

COPY src ./src

# Dağıtım varsayılanları — TEK yazıldıkları yer. Sunucu bunları
# hezarfen_rag.env (env_file) ile ezer.
# (Korpus seçimi — BOOK_PATH/SINIF/DERS — compose.yaml'da interpolasyon
# varsayılanı olarak durur: cihaza özel oldukları için dağıtım dosyasından
# gelirler.)
#
# SAĞLAYICI VARSAYILANI = api (deploy lane, 2026-09-17). Gerekçe ölçülmüş:
# yerel yol 7,6 GiB'lik VPS'e sığmıyor (BGE-M3 ~2,2 GB + reranker ~1,0 GB
# indirme + GPU'suz makinede rerank 95,9 s; kapı O-05 p50 ≤ 6 s). API yolu
# zarfı: torch ~0,4 GB + 0,53 GB/10k chunk → 1,1-2,6 GB (PROJECT_STATE §11.2).
# Operatör yerel yola dönmek isterse bu iki anahtarı `local` yapar; kod içi
# fabrika varsayılanı (src/embed/provider.py) DEĞİŞMEZ — ölçülmüş kalite
# sayıları yerel yola aittir ve eval koşuları env'siz çalışır.
ENV HF_HOME=/models \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    RAG_EMBED_PROVIDER=api \
    RAG_RERANK_PROVIDER=api

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
