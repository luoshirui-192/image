"""Rewrite SELECT * to exclude BLOB columns for faster raw SQL execution."""
from __future__ import annotations

import re

from django.db import connections

from images.blob_migration_service import BLOB_TYPES_MYSQL

_SELECT_STAR_RE = re.compile(
    r"^\s*(select)\s+\*\s+from\s+((?:[`\"]?[\w]+[`\"]?)\.)?[`\"]?([\w]+)[`\"]?",
    re.IGNORECASE,
)


def _normalize_table(name: str) -> str:
    return (name or "").strip().strip("`").split(".")[-1]


def _mysql_blob_columns(conn, *, database: str, table: str) -> set[str]:
    if conn.vendor != "mysql":
        return set()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COLUMN_NAME, LOWER(DATA_TYPE)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
            """,
            [database, table],
        )
        rows = cursor.fetchall()
    blob_types = {t.lower() for t in BLOB_TYPES_MYSQL}
    return {name for name, dtype in rows if (dtype or "").lower() in blob_types}


def _mysql_all_columns(conn, *, database: str, table: str) -> list[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
            """,
            [database, table],
        )
        return [row[0] for row in cursor.fetchall()]


def rewrite_select_star_exclude_blobs(
    sql: str,
    *,
    conn,
    database: str,
) -> tuple[str, bool]:
    """
    Replace `SELECT * FROM tbl` with explicit non-BLOB columns.

    Returns (sql, rewritten).
    """
    match = _SELECT_STAR_RE.match(sql.strip())
    if not match:
        return sql, False

    table = _normalize_table(match.group(3))
    db_name = (database or "").strip() or str(conn.settings_dict.get("NAME") or "")
    if not db_name or not table:
        return sql, False

    all_cols = _mysql_all_columns(conn, database=db_name, table=table)
    if not all_cols:
        return sql, False

    blob_cols = _mysql_blob_columns(conn, database=db_name, table=table)
    keep = [c for c in all_cols if c not in blob_cols]
    if not keep or len(keep) == len(all_cols):
        return sql, False

    quoted = ", ".join(f"`{col}`" for col in keep)
    suffix = sql[match.end() :]
    rewritten = f"SELECT {quoted} FROM `{table}`{suffix}"
    return rewritten, True
