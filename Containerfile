# hezarfen_rag — RAG servisi konteyneri (Podman; Docker DEĞİL)
# Not: Servis girişi (QUIC api-read) Faz 1 sonrası eklenecek; bu imge altyapı
# hazırlığıdır (bağımlılıklar + hazırlık kontrolü).
FROM docker.io/library/python:3.11-slim

WORKDIR /app

# Konteynerde CPU torch (yerel geliştirmede GPU/cu124 kullanılır; GPU passthrough
# ayrı kurulum ister). requirements'taki torch>=2.6 bu CPU wheel ile karşılanır,
# cu124 tekrar indirilmez.
COPY requirements.txt .
RUN pip install --no-cache-dir torch>=2.6 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY tests ./tests

# BGE-M3 modeli ilk çalıştırmada indirilir → HF_HOME kalıcı volume'a bağlanır.
ENV HF_HOME=/models \
    PYTHONUNBUFFERED=1

# Servis girişi henüz yok. Hazırlık kontrolü (import + sürüm).
CMD ["python", "-c", "import src; print('hezarfen_rag hazir — RAG servis girisi Faz 1 sonrasi eklenecek')"]
