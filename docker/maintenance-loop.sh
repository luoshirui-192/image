#!/bin/bash
# Periodic maintenance + BLOB migration job worker inside Docker scheduler container.
set -eu

cd /app/backend

INTERVAL_HOURS="${MAINTENANCE_INTERVAL_HOURS:-24}"
MIGRATION_POLL_SEC="${BLOB_MIGRATION_POLL_SECONDS:-30}"
if ! [[ "$INTERVAL_HOURS" =~ ^[0-9]+$ ]] || [ "$INTERVAL_HOURS" -lt 1 ]; then
  echo "[scheduler] invalid MAINTENANCE_INTERVAL_HOURS=$INTERVAL_HOURS, using 24" >&2
  INTERVAL_HOURS=24
fi
if ! [[ "$MIGRATION_POLL_SEC" =~ ^[0-9]+$ ]] || [ "$MIGRATION_POLL_SEC" -lt 5 ]; then
  echo "[scheduler] invalid BLOB_MIGRATION_POLL_SECONDS=$MIGRATION_POLL_SEC, using 30" >&2
  MIGRATION_POLL_SEC=30
fi
MAINTENANCE_INTERVAL_SEC=$((INTERVAL_HOURS * 3600))

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

echo "==> reclaim orphaned migration/export jobs"
python manage.py reclaim_blob_migration_jobs --no-kick || true
python manage.py reclaim_blob_export_jobs --no-kick || true

run_maintenance() {
  echo "==> $(date -Iseconds) run_scheduled_maintenance"
  python manage.py run_scheduled_maintenance
}

run_migration_jobs() {
  python manage.py process_blob_migration_jobs --once --max-jobs 1
}

run_export_jobs() {
  python manage.py process_blob_export_jobs --once --max-jobs 1
}

run_blob_sync() {
  python manage.py process_blob_sync --once --max-sources 1
}

echo "==> scheduler started (maintenance every ${INTERVAL_HOURS}h, migration poll every ${MIGRATION_POLL_SEC}s)"

last_maintenance_epoch=$(date +%s)

while true; do
  if run_migration_jobs; then
    :
  else
    echo "[scheduler] migration job worker failed (will retry)" >&2
  fi

  if run_export_jobs; then
    :
  else
    echo "[scheduler] export job worker failed (will retry)" >&2
  fi

  if run_blob_sync; then
    :
  else
    echo "[scheduler] blob sync worker failed (will retry)" >&2
  fi

  now_epoch=$(date +%s)
  elapsed=$((now_epoch - last_maintenance_epoch))
  if [ "$elapsed" -ge "$MAINTENANCE_INTERVAL_SEC" ]; then
    if run_maintenance; then
      echo "[scheduler] maintenance ok"
    else
      echo "[scheduler] maintenance failed (will retry next interval)" >&2
    fi
    last_maintenance_epoch=$(date +%s)
  fi

  sleep "$MIGRATION_POLL_SEC"
done
