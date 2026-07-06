#!/usr/bin/env bash
# 机器 A 一键启动：MySQL + Web + Backend + Scheduler（图片存储：MinIO S3）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
COMPOSE_FILE="docker-compose.app.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "请先安装 Docker: https://docs.docker.com/get-docker/"
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.app.example .env
  echo "已创建 .env（来自 .env.app.example）"
  echo "请编辑 MYSQL_* 密码、PUBLIC_URL、MINIO_* 后重新运行本脚本。"
  exit 0
fi

if ! grep -q '^MYSQL_ROOT_PASSWORD=.' .env || ! grep -q '^MYSQL_PASSWORD=.' .env; then
  echo "错误: .env 中须设置 MYSQL_ROOT_PASSWORD 与 MYSQL_PASSWORD"
  exit 1
fi

if ! grep -q '^PUBLIC_URL=' .env; then
  echo "错误: .env 缺少 PUBLIC_URL"
  exit 1
fi

# shellcheck disable=SC1091
set -a
source <(grep -v '^#' .env | grep -v '^$' | sed 's/\r$//')
set +a

STORAGE_BACKEND="${STORAGE_BACKEND:-minio}"
if [ "$STORAGE_BACKEND" = "minio" ]; then
  if [ -z "${MINIO_ACCESS_KEY:-}" ] || [ -z "${MINIO_SECRET_KEY:-}" ]; then
    echo "错误: STORAGE_BACKEND=minio 时须设置 MINIO_ACCESS_KEY 与 MINIO_SECRET_KEY"
    exit 1
  fi
  ENDPOINT="${MINIO_ENDPOINT:-http://192.168.9.100:9000}"
  echo "图片存储: MinIO ${ENDPOINT} / ${MINIO_BUCKET:-biox}/${MINIO_PREFIX:-data/image_db}"
else
  if [ ! -d upload ]; then
    mkdir -p upload
    echo "已创建 upload/ 目录（STORAGE_BACKEND=local）。"
  fi
fi

python3 docker/set-env.py
docker compose -f "$COMPOSE_FILE" up -d --build

echo ""
echo "=========================================="
echo " 机器 A 已启动（MySQL + 应用层）"
PUBLIC_URL="$(grep '^PUBLIC_URL=' .env | cut -d= -f2- | tr -d '\r')"
echo " 浏览器访问: ${PUBLIC_URL:-http://localhost}"
echo " MySQL: 本机 Docker 容器 db（127.0.0.1:${MYSQL_PUBLISH_PORT:-3306}）"
echo " 图片存储: ${STORAGE_BACKEND}（minio 见 MINIO_ENDPOINT）"
echo " 默认账号: admin / admin123"
echo " 停止: docker compose -f $COMPOSE_FILE down"
echo " 详细说明: README-MACHINE-A.md"
echo "=========================================="
