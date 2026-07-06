#!/usr/bin/env bash
# 机器 A 一键启动：MySQL + Web + Backend + Scheduler（upload 需挂载机器 B 的 NFS）
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
  echo "请编辑 MYSQL_* 密码、PUBLIC_URL、MACHINE_B_NFS_* 后重新运行本脚本。"
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

if [ ! -d upload ]; then
  mkdir -p upload
  echo "已创建 upload/ 目录。"
fi

if ! mountpoint -q upload 2>/dev/null; then
  NFS_HOST="${MACHINE_B_NFS_HOST:-}"
  NFS_PATH="${MACHINE_B_NFS_PATH:-/data/image_db/upload}"
  echo "警告: ./upload 当前不是 NFS 挂载点。"
  if [ -n "$NFS_HOST" ]; then
    echo "  生产环境请先挂载机器 B："
    echo "  sudo mount -t nfs ${NFS_HOST}:${NFS_PATH} $(pwd)/upload"
  fi
  echo "  继续启动将使用本地 upload/（仅适合测试）。"
fi

python3 docker/set-env.py
docker compose -f "$COMPOSE_FILE" up -d --build

echo ""
echo "=========================================="
echo " 机器 A 已启动（MySQL + 应用层）"
PUBLIC_URL="$(grep '^PUBLIC_URL=' .env | cut -d= -f2- | tr -d '\r')"
echo " 浏览器访问: ${PUBLIC_URL:-http://localhost}"
echo " MySQL: 本机 Docker 容器 db（127.0.0.1:${MYSQL_PUBLISH_PORT:-3306}）"
echo " 图片目录: ./upload（应挂载机器 B 的 NFS）"
echo " 默认账号: admin / admin123"
echo " 停止: docker compose -f $COMPOSE_FILE down"
echo " 详细说明: README-MACHINE-A.md"
echo "=========================================="
