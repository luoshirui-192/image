"""Auto-detect change-tracking columns on external source tables."""
from __future__ import annotations

from django.db import connections

from images.blob_sync_constants import CHANGE_TRACK_HASH, CHANGE_TRACK_TIMESTAMP, TIMESTAMP_COLUMN_CANDIDATES


def list_remote_column_names(conn, table: str) -> set[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
            """,
            [table],
        )
        return {str(row[0]).lower() for row in cursor.fetchall()}


def detect_change_track_mode(column_names: set[str]) -> tuple[str, str]:
    """Return (change_track_mode, change_track_column)."""
    for candidate in TIMESTAMP_COLUMN_CANDIDATES:
        if candidate in column_names:
            # Preserve actual casing from DB when possible — use lowercase for SQL.
            return CHANGE_TRACK_TIMESTAMP, candidate
    return CHANGE_TRACK_HASH, ""


def detect_change_track_for_table(conn, table: str) -> tuple[str, str]:
    return detect_change_track_mode(list_remote_column_names(conn, table))


def refresh_source_change_track(source, *, conn_alias: str) -> tuple[str, str]:
    """Detect and optionally persist change track fields on a migration source."""
    from images.models import BlobMigrationSource

    conn = connections[conn_alias]
    mode, column = detect_change_track_for_table(conn, source.source_table)
    if source.pk:
        BlobMigrationSource.objects.filter(pk=source.pk).update(
            change_track_mode=mode,
            change_track_column=column or "",
        )
    source.change_track_mode = mode
    source.change_track_column = column or ""
    return mode, column
