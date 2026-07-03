#!/usr/bin/env bash
# 机器 A 一键启动：Web + Backend + Scheduler（不含 MySQL 容器）
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
  echo "请编辑 DB_HOST、MYSQL_PASSWORD、PUBLIC_URL 等后重新运行本脚本。"
  exit 0
fi

DB_HOST="$(grep '^DB_HOST=' .env | cut -d= -f2- | tr -d '\r' || true)"
if [ -z "$DB_HOST" ] || [ "$DB_HOST" = "db" ] || [ "$DB_HOST" = "localhost" ] || [ "$DB_HOST" = "127.0.0.1" ]; then
  echo "错误: .env 中 DB_HOST 必须设为机器 B 的 MySQL 地址（当前: ${DB_HOST:-空}）"
  echo "详见 README-MACHINE-A.md"
  exit 1
fi

if [ ! -d upload ]; then
  mkdir -p upload
  echo "已创建 upload/ 目录。生产环境请挂载机器 B 的 NFS 到此目录。"
fi

if ! grep -q '^PUBLIC_URL=' .env; then
  echo "错误: .env 缺少 PUBLIC_URL"
  exit 1
fi

python3 docker/set-env.py
docker compose -f "$COMPOSE_FILE" up -d --build

echo ""
echo "=========================================="
echo " 机器 A 应用层已启动"
PUBLIC_URL="$(grep '^PUBLIC_URL=' .env | cut -d= -f2- | tr -d '\r')"
echo " 浏览器访问: ${PUBLIC_URL:-http://localhost}"
echo " 主库 MySQL: ${DB_HOST}"
echo " 默认账号: admin / admin123（需机器 B 已初始化 seed 数据）"
echo " 停止: docker compose -f $COMPOSE_FILE down"
echo " 详细说明: README-MACHINE-A.md"
echo "=========================================="
