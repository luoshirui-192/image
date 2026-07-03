#!/bin/bash
# Periodic maintenance inside Docker: purge old operate_log, legacy soft-deleted images.
set -eu

cd /app/backend

INTERVAL_HOURS="${MAINTENANCE_INTERVAL_HOURS:-24}"
if ! [[ "$INTERVAL_HOURS" =~ ^[0-9]+$ ]] || [ "$INTERVAL_HOURS" -lt 1 ]; then
  echo "[scheduler] invalid MAINTENANCE_INTERVAL_HOURS=$INTERVAL_HOURS, using 24" >&2
  INTERVAL_HOURS=24
fi
INTERVAL_SEC=$((INTERVAL_HOURS * 3600))

echo "==> scheduler waiting for MySQL..."
python - <<'PY'
import os
import sys
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

for _ in range(90):
    try:
        import django

        django.setup()
        from django.db import connection

        connection.ensure_connection()
        print("[scheduler] database connected")
        sys.exit(0)
    except Exception as exc:
        print(f"[scheduler] wait: {exc}")
        time.sleep(2)

print("[scheduler] database not ready", file=sys.stderr)
sys.exit(1)
PY

run_maintenance() {
  echo "==> $(date -Iseconds) run_scheduled_maintenance"
  python manage.py run_scheduled_maintenance
}

echo "==> scheduler started (every ${INTERVAL_HOURS}h, LOG_RETENTION_DAYS=${LOG_RETENTION_DAYS:-90})"

while true; do
  if run_maintenance; then
    echo "[scheduler] maintenance ok"
  else
    echo "[scheduler] maintenance failed (will retry next interval)" >&2
  fi
  echo "==> next run in ${INTERVAL_HOURS} hour(s)"
  sleep "$INTERVAL_SEC"
done
