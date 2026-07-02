#!/usr/bin/env bash
# GitHub 下载后一键启动（Linux / macOS，需已安装 Docker）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "请先安装 Docker: https://docs.docker.com/get-docker/"
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.docker.example .env
  echo "已创建 .env，请按需修改 PUBLIC_URL 与密钥后重新运行本脚本。"
fi

python3 docker/set-env.py
docker compose up -d --build

echo ""
echo "=========================================="
echo " 系统已启动"
PUBLIC_URL="$(grep '^PUBLIC_URL=' .env | cut -d= -f2- | tr -d '\r')"
echo " 浏览器访问: ${PUBLIC_URL:-http://localhost}"
echo " 默认账号: admin / admin123"
echo " 停止服务: docker compose down"
echo "=========================================="
