#!/usr/bin/env bash
# 兼容入口：若 MySQL 在本机 Docker 中，请改跑 Docker 版（推荐）:
#   ./scripts/provision_system_db_docker.sh --yes
#
# 本脚本通过 TCP 连 192.168.1.33（容器映射的端口），需要 python3+pymysql。
# Ubuntu 上请用:  python3 -m pip install --user pymysql
# 不要用 apt 的 python-pip（那是 Python 2）。

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "提示: MySQL 若跑在 Docker 里，推荐在 192.168.1.33 上执行:"
echo "  ./scripts/provision_system_db_docker.sh --yes"
echo "下面仍尝试用 TCP 连接（需 python3 + pymysql）..."
echo

HOST="${HOST:-192.168.1.33}"
PORT="${PORT:-3306}"
ADMIN_USER="${MYSQL_ADMIN_USER:-root}"
PASSWORD="${MYSQL_ROOT_PASSWORD:-}"
WRONG_DB="${WRONG_DB:-ara_fp_analyst}"
SYSTEM_DB="${SYSTEM_DB:-image_db}"
APP_USER="${MYSQL_USER:-image_db}"
APP_PASSWORD="${MYSQL_PASSWORD:-}"

EXTRA=()
for arg in "$@"; do
  EXTRA+=("$arg")
done

if [[ -z "$PASSWORD" ]]; then
  read -r -s -p "请输入 MySQL root@${HOST} 密码: " PASSWORD
  echo
fi

if ! python3 -c "import pymysql" 2>/dev/null && ! python3 -c "import MySQLdb" 2>/dev/null; then
  echo "缺少驱动。请执行（注意用 python3，不要用旧的 pip）:"
  echo "  python3 -m pip install --user pymysql"
  echo "或改用 Docker 版（无需 pip）:"
  echo "  ./scripts/provision_system_db_docker.sh --yes"
  exit 1
fi

python3 scripts/provision_system_db.py \
  --host "$HOST" \
  --port "$PORT" \
  --user "$ADMIN_USER" \
  --password "$PASSWORD" \
  --wrong-db "$WRONG_DB" \
  --system-db "$SYSTEM_DB" \
  --app-user "$APP_USER" \
  ${APP_PASSWORD:+--app-password "$APP_PASSWORD"} \
  "${EXTRA[@]}"
