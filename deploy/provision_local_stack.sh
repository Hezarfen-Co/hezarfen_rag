#!/usr/bin/env bash
# YEREL MODEL YIĞININI VOLUME'A SAĞLAR (küçük imge kararı, 2026-09-17).
#
# NEDEN: varsayılan imge KÜÇÜKTÜR — torch/FlagEmbedding/ağırlıklar içinde YOK
# (API sağlayıcı yolu). Yerel yola (`RAG_EMBED_PROVIDER=local`) geçmek imgeyi
# yeniden derlemeyi ya da workflow koşmayı GEREKTİRMEZ: bağımlılıklar bir
# podman VOLUME'undaki venv'de durur, servis onu mount edip `sys.path`e ekler.
#
# KULLANIM (VPS'te BİR KEZ; yeniden koşmak güvenli — idempotent):
#   bash deploy/provision_local_stack.sh                 # venv + bağımlılıklar
#   bash deploy/provision_local_stack.sh --agirliklari-indir   # + HF ağırlıkları
#
# Sonra ~/hezarfen_rag/hezarfen_rag.env içine (satır-içi `#` YORUM KOYMA):
#   RAG_EMBED_PROVIDER=local
#   RAG_RERANK_PROVIDER=local
#   RAG_LOCAL_VENV=/local-stack/venv
#   RAG_LOCAL_MODELS_DIR=/local-stack/models
# ve compose.yaml'a volume mount'u (README "yerel yola dönüş" bölümü).
# Değişikliği uygula:  systemctl --user restart hezarfen_rag_compose
#
# NOT: pip ve venv DAİMA servis imgesinin İÇİNDE çalışır (aşağıdaki `podman run`)
# — host'ta değil. Derlenmiş uzantılar (torch'un .so'ları) yalnız ABI/glibc
# etiketleri uyuşan yorumlayıcıda yüklenir; imge python'u 3.11 + bookworm ise
# volume'daki venv de tam olarak ona göre kurulmalı. Başka bir makinede kurulan
# venv kopyalanamaz.
#
# Volume'a sürüm işareti yazılır (PROVISIONED): servis "sağlanmış mı" sorusunu
# bununla cevaplar ve reddi mesajında eksik olduğunu adıyla söyler.
set -euo pipefail

# VOLUME ADI: compose.yaml'daki anahtar `rag-local`'dir ve compose onu proje adıyla
# ÖNEKLER (ör. hezarfen_rag_rag-local). Betik ÖNCE var olanı bulur; yoksa
# RAG_LOCAL_VOLUME verilmişse onu, o da yoksa `hezarfen_rag_local` yaratır ve
# uyarır (aksi halde servis "sağlanmamış" derdi — sessiz bir yanlış volume).
if [ -n "${RAG_LOCAL_VOLUME:-}" ]; then
  VOLUME=$RAG_LOCAL_VOLUME
else
  VOLUME=$(podman volume ls --format '{{.Name}}' 2>/dev/null | grep -E '(^|_)rag-local$' | head -1 || true)
  VOLUME=${VOLUME:-hezarfen_rag_local}
fi
echo "kullanılan volume: $VOLUME" 
IMAGE=${RAG_IMAGE:-localhost/hezarfen_rag:current}
TORCH_INDEX=${TORCH_INDEX:-https://download.pytorch.org/whl/cpu}
MONTAJ=/local-stack
AGIRLIK_INIR=0
for arg in "$@"; do
  case "$arg" in
    --agirliklari-indir) AGIRLIK_INIR=1 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "bilinmeyen argüman: $arg (geçerli: --agirliklari-indir)" >&2; exit 2 ;;
  esac
done

command -v podman >/dev/null || { echo "podman yok" >&2; exit 1; }
podman image exists "$IMAGE" || {
  echo "imaj yok: $IMAGE — önce imajı yükle (podman load) ya da RAG_IMAGE ver" >&2
  exit 1
}

# 1) Volume (idempotent).
podman volume exists "$VOLUME" || podman volume create "$VOLUME"

calistir() { podman run --rm -v "$VOLUME:$MONTAJ" "$@"; }

# 2) venv — İMGENİN python'u ile (sürüm uyuşmazlığı C uzantılarını bozar).
if [ ! -x "$(podman volume inspect -f '{{.Mountpoint}}' "$VOLUME")/venv/bin/pip" ]; then
  calistir "$IMAGE" python -m venv --system-site-packages "$MONTAJ/venv"
  echo "venv kuruldu: $VOLUME/venv"
fi

# 3) Yerel bağımlılıklar — CPU tekerleği AÇIK index ile (PyPI'daki varsayılan
#    linux `torch` tekerleği CUDA derlemesidir ve ~2-3 GB kurar).
calistir "$IMAGE" "$MONTAJ/venv/bin/pip" install --no-cache-dir \
  --index-url "$TORCH_INDEX" "torch>=2.6"
calistir "$IMAGE" "$MONTAJ/venv/bin/pip" install --no-cache-dir \
  -r /app/requirements-local.txt

# 3b) Sürüm işareti (idempotent: her koşuda tazelenir).
calistir "$IMAGE" sh -c "printf 'PROVISIONED_IMAGE=%s\nPROVISIONED_TAG=%s\nPYTHON=%s\nREQUIREMENTS_SHA256=%s\nDATE=%s\n' '%s' '%s' \"\$(python -c 'import platform;print(platform.python_version())')\" \"\$(sha256sum /app/requirements-local.txt | cut -c1-16)\" \"\$(date -Iseconds)\" > $MONTAJ/PROVISIONED"

# 4) Doğrula: bu, servisin açılışta yaptığı denetimin AYNISI.
calistir -e RAG_EMBED_PROVIDER=local -e RAG_RERANK_PROVIDER=local \
  -e "RAG_LOCAL_VENV=$MONTAJ/venv" -e "RAG_LOCAL_MODELS_DIR=$MONTAJ/models" \
  -e LLM_API_KEY=denetim "$IMAGE" python -m src.service.preflight

# 5) (ops.) Ağırlıkları ŞİMDİ indir (~4,5 GB) — yoksa ilk yerel istekte iner.
if [ "$AGIRLIK_INIR" = "1" ]; then
  calistir -e "RAG_LOCAL_VENV=$MONTAJ/venv" -e "RAG_LOCAL_MODELS_DIR=$MONTAJ/models" \
    "$IMAGE" "$MONTAJ/venv/bin/python" -c '
import os, sys
sys.path.insert(0, os.environ["RAG_LOCAL_VENV"] + "/lib/python" +
                "%d.%d" % sys.version_info[:2] + "/site-packages")
os.environ["HF_HOME"] = os.environ["RAG_LOCAL_MODELS_DIR"]
from src.embed.embedder import BGEM3Embedder
from src.rerank.reranker import BGEReranker
BGEM3Embedder().warmup(); BGEReranker().warmup()
print("ağırlıklar hazır:", os.environ["HF_HOME"])'
fi

cat <<EOF

Sağlama tamam. .env'e (satır-içi # yorum YOK) eklenecek satırlar:
  RAG_EMBED_PROVIDER=local
  RAG_RERANK_PROVIDER=local
  RAG_LOCAL_VENV=$MONTAJ/venv
  RAG_LOCAL_MODELS_DIR=$MONTAJ/models
compose.yaml'a mount: - $VOLUME:$MONTAJ:ro,z
Sonra: systemctl --user restart hezarfen_rag_compose
EOF
