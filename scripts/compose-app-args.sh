#!/usr/bin/env bash
# Emit docker compose -f arguments for machine A (app layer).
# Prefers docker-compose.app.override.yml, else USE_EXTERNAL_MYSQL=1 → external-db example.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${ROOT}/docker-compose.app.yml"
OVERRIDE_FILE="${ROOT}/docker-compose.app.override.yml"
EXTERNAL_FILE="${ROOT}/docker-compose.app.external-db.example.yml"
ENV_FILE="${ROOT}/.env"

args=(-f "$COMPOSE_FILE")

if [ -f "$OVERRIDE_FILE" ]; then
  args+=(-f "$OVERRIDE_FILE")
  echo "compose: 使用 docker-compose.app.override.yml（外部/自定义 MySQL）" >&2
elif [ -f "$ENV_FILE" ] && grep -qE '^USE_EXTERNAL_MYSQL=(1|true|yes|TRUE|YES)' "$ENV_FILE"; then
  if [ ! -f "$EXTERNAL_FILE" ]; then
    echo "错误: .env 中 USE_EXTERNAL_MYSQL=1，但缺少 ${EXTERNAL_FILE}" >&2
    exit 1
  fi
  args+=(-f "$EXTERNAL_FILE")
  echo "compose: USE_EXTERNAL_MYSQL=1，连接宿主机 MySQL（host.docker.internal:3306）" >&2
else
  echo "compose: 使用内置 db 容器（DB_HOST=db）" >&2
fi

printf '%s\n' "${args[@]}"
