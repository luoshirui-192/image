#!/usr/bin/env bash
# 机器 B 一键启动：仅 MySQL 数据容器
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
COMPOSE_FILE="docker-compose.data.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "请先安装 Docker: https://docs.docker.com/get-docker/"
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.data.example .env
  echo "已创建 .env（来自 .env.data.example）"
  echo "请编辑 MYSQL_* 密码、MACHINE_A_HOSTS、DATA_UPLOAD_ROOT 后重新运行。"
  exit 0
fi

if ! grep -q '^MYSQL_ROOT_PASSWORD=.' .env || ! grep -q '^MYSQL_PASSWORD=.' .env; then
  echo "错误: .env 中须设置 MYSQL_ROOT_PASSWORD 与 MYSQL_PASSWORD"
  exit 1
fi

# shellcheck disable=SC1091
set -a
source <(grep -v '^#' .env | grep -v '^$' | sed 's/\r$//')
set +a

UPLOAD_ROOT="${DATA_UPLOAD_ROOT:-/data/image_db/upload}"
if [ ! -d "$UPLOAD_ROOT" ]; then
  echo "创建图片目录: $UPLOAD_ROOT"
  sudo mkdir -p "$UPLOAD_ROOT"
  sudo chmod 1777 "$UPLOAD_ROOT"
fi

python3 docker/set-env.py 2>/dev/null || true

docker compose -f "$COMPOSE_FILE" up -d --build

echo ""
echo "等待 MySQL 就绪..."
for i in $(seq 1 60); do
  if docker compose -f "$COMPOSE_FILE" exec -T db mysqladmin ping -h 127.0.0.1 -uroot -p"${MYSQL_ROOT_PASSWORD}" --silent 2>/dev/null; then
    break
  fi
  sleep 2
done

echo ""
echo "=========================================="
echo " 机器 B MySQL 已启动"
echo " 库名: ${MYSQL_DATABASE:-image_db}"
echo " 端口: ${MYSQL_PUBLISH_PORT:-3306}（请防火墙仅放行机器 A）"
echo " 图片目录: $UPLOAD_ROOT"
echo ""
echo " 下一步（必做）："
echo "   1. ./scripts/grant-machine-a.sh   # 授权机器 A 连接 MySQL"
echo "   2. ./scripts/setup-nfs-export.sh  # 配置 NFS 导出 upload"
echo " 详细说明: README-MACHINE-B.md"
echo "=========================================="
