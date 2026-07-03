#!/usr/bin/env bash
# 为机器 A 创建/更新 MySQL 用户，允许远程连接主库
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "错误: 未找到 .env，请先 cp .env.data.example .env"
  exit 1
fi

# shellcheck disable=SC1091
set -a
source <(grep -v '^#' .env | grep -v '^$' | sed 's/\r$//')
set +a

HOSTS="${MACHINE_A_HOSTS:-}"
if [ -z "$HOSTS" ]; then
  echo "错误: .env 中 MACHINE_A_HOSTS 未设置（机器 A 的 IP）"
  exit 1
fi

COMPOSE="docker compose -f docker-compose.data.yml"
if ! $COMPOSE ps --status running db 2>/dev/null | grep -q db; then
  echo "错误: db 容器未运行，请先 ./start-data.sh"
  exit 1
fi

for APP_IP in $HOSTS; do
  echo "授权 ${MYSQL_USER}@${APP_IP} ..."
  $COMPOSE exec -T db mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" <<EOF
CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'${APP_IP}' IDENTIFIED BY '${MYSQL_PASSWORD}';
GRANT ALL PRIVILEGES ON \`${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'${APP_IP}';
FLUSH PRIVILEGES;
EOF
done

echo "完成。机器 A 可使用 DB_HOST=$(hostname -I | awk '{print $1}') 连接。"
