"""MySQL session time helpers — align upload_time with NOW() / CURRENT_TIMESTAMP."""
from __future__ import annotations

from django.db import connection
from django.utils import timezone


def fetch_db_now():
    """
    Return current local time as timezone-aware datetime (Asia/Shanghai).

    MySQL uses SELECT NOW() in session timezone (+08:00 via init_command).
    """
    if connection.vendor == "sqlite":
        return timezone.localtime()

    with connection.cursor() as cursor:
        cursor.execute("SELECT NOW()")
        row = cursor.fetchone()
    if row is None or row[0] is None:
        raise RuntimeError("SELECT NOW() returned no value")
    naive = row[0]
    if timezone.is_naive(naive):
        return timezone.make_aware(naive, timezone.get_current_timezone())
    return timezone.localtime(naive)
