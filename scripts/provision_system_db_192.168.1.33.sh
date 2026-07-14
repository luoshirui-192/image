#!/usr/bin/env bash
# 一键：在 192.168.1.33 新建系统库 image_db，并把 ara_fp_analyst 里的系统表迁出
# 用法:
#   export MYSQL_ROOT_PASSWORD='你的root密码'
#   ./scripts/provision_system_db_192.168.1.33.sh
#   ./scripts/provision_system_db_192.168.1.33.sh --dry-run
#   ./scripts/provision_system_db_192.168.1.33.sh --yes

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

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
