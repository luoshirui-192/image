#!/bin/bash
set -eu

cd /app/backend

echo "==> waiting for MySQL..."
python - <<'PY'
import os
import sys
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

for i in range(90):
    try:
        import django

        django.setup()
        from django.db import connection

        connection.ensure_connection()
        print("[ok] database connected")
        sys.exit(0)
    except Exception as exc:
        print(f"[wait] {exc}")
        time.sleep(2)

print("[fail] database not ready", file=sys.stderr)
sys.exit(1)
PY

echo "==> migrate"
python manage.py migrate --fake-initial --noinput

echo "==> ensure mysql triggers"
python /app/docker/ensure_mysql57_triggers.py

echo "==> ensure file_hash column"
python /app/docker/ensure_file_hash_column.py

echo "==> start gunicorn"
exec gunicorn -c /app/deploy/gunicorn/gunicorn.conf.py config.wsgi:application
