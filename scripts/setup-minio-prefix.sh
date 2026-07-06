#!/usr/bin/env bash
# 在机器 B（或任意能访问 MinIO VIP 的管理机）上初始化 biox 桶内 image_db 前缀
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -v '^\s*#' .env | sed '/^\s*$/d' | sed 's/\r$//')
  set +a
fi

ALIAS="${MINIO_MC_ALIAS:-aratek}"
ENDPOINT="${MINIO_ENDPOINT:-http://192.168.9.9:9000}"
ACCESS_KEY="${MINIO_ACCESS_KEY:-}"
SECRET_KEY="${MINIO_SECRET_KEY:-}"
BUCKET="${MINIO_BUCKET:-biox}"
PREFIX="${MINIO_PREFIX:-data/image_db}"

if [[ -z "$ACCESS_KEY" || -z "$SECRET_KEY" ]]; then
  echo "错误: 请在 .env 中设置 MINIO_ACCESS_KEY / MINIO_SECRET_KEY"
  exit 1
fi

if ! command -v mc >/dev/null 2>&1; then
  echo "错误: 未找到 mc，请先安装 MinIO Client: https://min.io/docs/minio/linux/reference/minio-mc.html"
  exit 1
fi

mc alias set "$ALIAS" "$ENDPOINT" "$ACCESS_KEY" "$SECRET_KEY"

KEEP_FILE="${PREFIX%/}/.keep"
echo "ok" | mc pipe "${ALIAS}/${BUCKET}/${KEEP_FILE}"

echo ""
echo "MinIO 前缀已初始化: ${ALIAS}/${BUCKET}/${PREFIX}/"
echo "对象路径示例: ${PREFIX}/upload/YYYYMMDD/category_id/uuid.jpg"
echo ""
echo "请将以下信息交给机器 A 管理员（写入 .env）："
echo "  STORAGE_BACKEND=minio"
echo "  MINIO_ENDPOINT=${ENDPOINT}"
echo "  MINIO_BUCKET=${BUCKET}"
echo "  MINIO_PREFIX=${PREFIX}"
