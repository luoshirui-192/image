"""Rewrite SELECT queries to avoid transferring BLOB bytes over the wire."""
from __future__ import annotations

import re
from dataclasses import dataclass

from images.blob_migration_service import BLOB_TYPES_MYSQL

_SELECT_STAR_RE = re.compile(
    r"^\s*(select)\s+\*\s+from\s+((?:[`\"]?[\w]+[`\"]?)\.)?[`\"]?([\w]+)[`\"]?",
    re.IGNORECASE,
)

_SELECT_FROM_RE = re.compile(
    r"^\s*(select)\s+(.+?)\s+\bfrom\s+((?:[`\"]?[\w]+[`\"]?)\.)?[`\"]?([\w]+)[`\"]?",
    re.IGNORECASE | re.DOTALL,
)

_SIMPLE_COL_RE = re.compile(
    r"^(?:[`\"]?([\w]+)[`\"]?)(?:\s*\.\s*[`\"]?([\w]+)[`\"]?)?(?:\s+(?:as\s+)?[`\"]?([\w]+)[`\"]?)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SqlBlobRewrite:
    sql: str
    rewritten: bool
    blob_length_columns: frozenset[str] = frozenset()


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


def _split_select_columns(column_sql: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for idx, ch in enumerate(column_sql):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            part = column_sql[start:idx].strip()
            if part:
                parts.append(part)
            start = idx + 1
    tail = column_sql[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_simple_column(expr: str) -> tuple[str, str] | None:
    """Return (source_column, output_alias) for a simple column reference."""
    cleaned = expr.strip()
    if not cleaned or "*" in cleaned:
        return None
    upper = cleaned.upper()
    if upper.startswith("DISTINCT "):
        cleaned = cleaned[9:].strip()
    if any(
        token in upper
        for token in ("(", ")", " CASE", " WHEN", " SUBSTRING", " CONCAT", " CAST", " COALESCE")
    ):
        return None
    match = _SIMPLE_COL_RE.match(cleaned)
    if not match:
        return None
    table_part, col_part, alias_part = match.groups()
    source_col = col_part or table_part
    if not source_col:
        return None
    alias = alias_part or source_col
    return source_col, alias


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
    result = rewrite_sql_for_blob_performance(sql, conn=conn, database=database)
    return result.sql, result.rewritten and not result.blob_length_columns


def rewrite_sql_for_blob_performance(
    sql: str,
    *,
    conn,
    database: str,
) -> SqlBlobRewrite:
    """
    Optimize SELECT for BLOB tables:
    - SELECT * → explicit non-BLOB columns
    - explicit BLOB columns → OCTET_LENGTH(col) AS col (size only, no bytes)
    """
    cleaned = sql.strip()
    star_match = _SELECT_STAR_RE.match(cleaned)
    if star_match:
        table = _normalize_table(star_match.group(3))
        db_name = (database or "").strip() or str(conn.settings_dict.get("NAME") or "")
        if db_name and table:
            all_cols = _mysql_all_columns(conn, database=db_name, table=table)
            blob_cols = _mysql_blob_columns(conn, database=db_name, table=table)
            keep = [c for c in all_cols if c not in blob_cols]
            if keep and blob_cols and len(keep) < len(all_cols):
                quoted = ", ".join(f"`{col}`" for col in keep)
                suffix = cleaned[star_match.end() :]
                rewritten = f"SELECT {quoted} FROM `{table}`{suffix}"
                return SqlBlobRewrite(sql=rewritten, rewritten=True)

    from_match = _SELECT_FROM_RE.match(cleaned)
    if not from_match or conn.vendor != "mysql":
        return SqlBlobRewrite(sql=sql, rewritten=False)

    column_sql = from_match.group(2).strip()
    if "*" in column_sql:
        return SqlBlobRewrite(sql=sql, rewritten=False)

    table = _normalize_table(from_match.group(4))
    db_name = (database or "").strip() or str(conn.settings_dict.get("NAME") or "")
    if not db_name or not table:
        return SqlBlobRewrite(sql=sql, rewritten=False)

    blob_cols = _mysql_blob_columns(conn, database=db_name, table=table)
    if not blob_cols:
        return SqlBlobRewrite(sql=sql, rewritten=False)

    rewritten_parts: list[str] = []
    length_columns: set[str] = set()
    changed = False

    for expr in _split_select_columns(column_sql):
        parsed = _parse_simple_column(expr)
        if parsed is None:
            rewritten_parts.append(expr)
            continue
        source_col, alias = parsed
        if source_col not in blob_cols:
            rewritten_parts.append(expr)
            continue
        quoted = f"`{source_col}`"
        rewritten_parts.append(f"OCTET_LENGTH({quoted}) AS `{alias}`")
        length_columns.add(alias)
        changed = True

    if not changed:
        return SqlBlobRewrite(sql=sql, rewritten=False)

    suffix = cleaned[from_match.end() :]
    rewritten = f"SELECT {', '.join(rewritten_parts)} FROM `{table}`{suffix}"
    return SqlBlobRewrite(
        sql=rewritten,
        rewritten=True,
        blob_length_columns=frozenset(length_columns),
    )
