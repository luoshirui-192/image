#!/usr/bin/env bash
# 机器 A 一键启动：MySQL + Web + Backend + Scheduler（图片存储：MinIO S3）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "请先安装 Docker: https://docs.docker.com/get-docker/"
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.app.example .env
  echo "已创建 .env（来自 .env.app.example）"
  echo "请编辑 MYSQL_* / DB_HOST / PUBLIC_URL、MINIO_* 后重新运行本脚本。"
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
  ENDPOINT="${MINIO_ENDPOINT:-http://192.168.9.9:9000}"
  echo "图片存储: MinIO ${ENDPOINT} / ${MINIO_BUCKET:-biox}/${MINIO_PREFIX:-data/image_db}"
else
  if [ ! -d upload ]; then
    mkdir -p upload
    echo "已创建 upload/ 目录（STORAGE_BACKEND=local）。"
  fi
fi

python3 docker/set-env.py

COMPOSE_ARGS=()
while IFS= read -r line; do
  COMPOSE_ARGS+=("$line")
done < <(bash scripts/compose-app-args.sh 2>/dev/null)

# 外部 MySQL：确保宿主机库在跑，停掉可能冲突的内置 db
DB_HOST_VAL="${DB_HOST:-db}"
if [ "$DB_HOST_VAL" != "db" ] || [ -f docker-compose.app.override.yml ] || grep -qE '^USE_EXTERNAL_MYSQL=(1|true|yes)' .env 2>/dev/null; then
  echo "外部 MySQL 模式: DB_HOST=${DB_HOST_VAL}"
  if docker ps -a --format '{{.Names}}' | grep -qx 'mysql8039'; then
    docker start mysql8039 2>/dev/null || true
    echo "已尝试启动 mysql8039"
  fi
  docker compose -f docker-compose.app.yml stop db 2>/dev/null || true
fi

docker compose "${COMPOSE_ARGS[@]}" up -d --build

echo ""
echo "=========================================="
echo " 机器 A 已启动"
PUBLIC_URL="$(grep '^PUBLIC_URL=' .env | cut -d= -f2- | tr -d '\r')"
echo " 浏览器: ${PUBLIC_URL:-http://localhost}"
if [ "$DB_HOST_VAL" != "db" ]; then
  echo " MySQL: 宿主机 (${DB_HOST_VAL}:3306) — 数据在 mysql8039 等现有库"
else
  echo " MySQL: compose 内置 db"
fi
echo ""
echo " 诊断: bash scripts/diagnose-machine-a.sh"
echo " 停止: docker compose ${COMPOSE_ARGS[*]} down"
echo "=========================================="
