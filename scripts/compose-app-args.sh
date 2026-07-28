#!/usr/bin/env bash
# Emit docker compose -f / --profile arguments for machine A.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${ROOT}/docker-compose.app.yml"
OVERRIDE_FILE="${ROOT}/docker-compose.app.override.yml"
EXTERNAL_FILE="${ROOT}/docker-compose.app.external-db.example.yml"
ENV_FILE="${ROOT}/.env"

args=(-f "$COMPOSE_FILE")

if [ -f "$OVERRIDE_FILE" ]; then
  args+=(-f "$OVERRIDE_FILE")
  echo "compose: override.yml" >&2
elif [ -f "$ENV_FILE" ] && grep -qE '^USE_EXTERNAL_MYSQL=(1|true|yes|TRUE|YES)' "$ENV_FILE"; then
  args+=(-f "$EXTERNAL_FILE")
  echo "compose: USE_EXTERNAL_MYSQL" >&2
fi

# Builtin db profile unless external MySQL
use_builtin=1
if [ -f "$OVERRIDE_FILE" ] || { [ -f "$ENV_FILE" ] && grep -qE '^USE_EXTERNAL_MYSQL=(1|true|yes|TRUE|YES)' "$ENV_FILE"; }; then
  use_builtin=0
elif [ -f "$ENV_FILE" ]; then
  db_host="$(grep -E '^DB_HOST=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r' | xargs || true)"
  if [ -n "$db_host" ] && [ "$db_host" != "db" ]; then
    use_builtin=0
    echo "compose: DB_HOST=${db_host}（不启动内置 db）" >&2
  fi
fi

if [ "$use_builtin" -eq 1 ]; then
  args+=(--profile with-builtin-mysql)
  echo "compose: 内置 db 容器" >&2
else
  echo "compose: 外部 MySQL" >&2
fi

printf '%s\n' "${args[@]}"
