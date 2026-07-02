#!/usr/bin/env bash
# 步骤 29 — 前台启动 Gunicorn（Linux 服务器调试用）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
CONF="$ROOT/deploy/gunicorn/gunicorn.conf.py"

if [[ ! -f "$CONF" ]]; then
  echo "缺少 Gunicorn 配置: $CONF" >&2
  exit 1
fi

# 优先 deploy/paths.env，否则 example
PATHS_FILE="$ROOT/deploy/paths.env"
if [[ ! -f "$PATHS_FILE" ]]; then
  PATHS_FILE="$ROOT/deploy/paths.env.example"
fi

if [[ -f "$PATHS_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a
  source <(grep -E '^[A-Z_]+=' "$PATHS_FILE" | sed 's/\r$//')
  set +a
fi

VENV_BIN="${VENV_PATH:-$ROOT/.venv}/bin"
GUNICORN="$VENV_BIN/gunicorn"

if [[ ! -x "$GUNICORN" ]]; then
  GUNICORN="$(command -v gunicorn || true)"
fi

if [[ -z "$GUNICORN" ]]; then
  echo "未找到 gunicorn，请执行: pip install -r backend/requirements-production.txt" >&2
  exit 1
fi

export GUNICORN_BIND="${GUNICORN_BIND:-${BACKEND_UPSTREAM:-127.0.0.1:8000}}"
echo "启动 Gunicorn bind=$GUNICORN_BIND (cwd=$BACKEND)"
exec "$GUNICORN" -c "$CONF" config.wsgi:application
