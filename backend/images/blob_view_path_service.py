"""Resolve SQL VIEW → base table for path lookup (PR2)."""
from __future__ import annotations

import logging
import re
from typing import Any

from images.blob_schema_helpers import OBJECT_TYPE_TABLE, OBJECT_TYPE_VIEW, normalize_object_type

logger = logging.getLogger(__name__)

# First table after FROM in a simple view definition (handles `db`.`tbl` and backticks).
_SIMPLE_FROM_RE = re.compile(
    r"\bFROM\s+(?:`?(?P<db>[a-zA-Z_][a-zA-Z0-9_]*)`?\s*\.\s*)?`?(?P<table>[a-zA-Z_][a-zA-Z0-9_]*)`?",
    re.IGNORECASE,
)


class BlobViewPathError(Exception):
    pass


def _validate_identifier(name: str, *, label: str = "标识符") -> str:
    from images.blob_migration_service import validate_identifier

    return validate_identifier(name, label=label)


def detect_mysql_object_type(conn, *, database: str, object_name: str) -> str:
    """Return OBJECT_TYPE_TABLE or OBJECT_TYPE_VIEW."""
    table = _validate_identifier(object_name, label="对象名")
    db_name = _validate_identifier(database, label="数据库名") if database else None
    if conn.vendor != "mysql":
        return OBJECT_TYPE_TABLE

    with conn.cursor() as cursor:
        if db_name:
            cursor.execute(
                """
                SELECT TABLE_TYPE
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                LIMIT 1
                """,
                [db_name, table],
            )
        else:
            cursor.execute(
                """
                SELECT TABLE_TYPE
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                LIMIT 1
                """,
                [table],
            )
        row = cursor.fetchone()
    if not row:
        raise BlobViewPathError(f"对象不存在: {object_name}")
    return OBJECT_TYPE_VIEW if row[0] == "VIEW" else OBJECT_TYPE_TABLE


def parse_simple_view_base_table(view_definition: str) -> str | None:
    """Best-effort: extract the first base table from a simple SELECT … FROM … view."""
    if not view_definition:
        return None
    normalized = " ".join(view_definition.split())
    if re.search(r"\b(JOIN|UNION)\b", normalized, re.IGNORECASE):
        return None
    match = _SIMPLE_FROM_RE.search(normalized)
    if not match:
        return None
    try:
        return _validate_identifier(match.group("table"), label="基表名")
    except Exception:
        return None


def resolve_path_lookup_table(
    conn,
    *,
    database: str,
    object_name: str,
    object_type: str | None = None,
    manual: str | None = None,
) -> str:
    """
    Resolve where image_source_map.source_table should point for browse/migrate.

    Tables use their own name; views use the detected base table (or manual override).
    """
    table = _validate_identifier(object_name, label="对象名")
    normalized_type = normalize_object_type(object_type) if object_type else None

    manual_value = (manual or "").strip()
    if manual_value:
        return _validate_identifier(manual_value, label="路径映射表")

    if normalized_type is None and conn.vendor == "mysql":
        normalized_type = detect_mysql_object_type(conn, database=database, object_name=table)
    elif normalized_type is None:
        normalized_type = OBJECT_TYPE_TABLE

    if normalized_type != OBJECT_TYPE_VIEW:
        return table

    if conn.vendor != "mysql":
        raise BlobViewPathError("非 MySQL 的数据库视图需手动指定 path_lookup_table")

    db_name = _validate_identifier(database, label="数据库名") if database else None
    with conn.cursor() as cursor:
        if db_name:
            cursor.execute(
                """
                SELECT VIEW_DEFINITION
                FROM information_schema.VIEWS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                LIMIT 1
                """,
                [db_name, table],
            )
        else:
            cursor.execute(
                """
                SELECT VIEW_DEFINITION
                FROM information_schema.VIEWS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                LIMIT 1
                """,
                [table],
            )
        row = cursor.fetchone()

    if not row or not row[0]:
        raise BlobViewPathError(f"无法读取视图定义: {table}")

    base = parse_simple_view_base_table(row[0])
    if not base:
        raise BlobViewPathError(
            f"无法自动识别视图 {table} 的基表，请在配置中手动填写 path_lookup_table"
        )
    logger.info("auto-detected path_lookup_table=%s for view=%s", base, table)
    return base


def resolve_source_metadata(
    conn,
    *,
    database: str,
    object_name: str,
    object_type: str | None = None,
    path_lookup_table: str | None = None,
    blob_columns: list[str] | None = None,
    blob_column: str | None = None,
) -> dict[str, Any]:
    """Normalize object_type + path_lookup_table for create source/view."""
    from images.blob_schema_helpers import parse_blob_columns, primary_blob_column, serialize_blob_columns

    cols = parse_blob_columns(
        serialize_blob_columns(blob_columns) if blob_columns else None,
        blob_column,
    )
    if not cols:
        raise BlobViewPathError("至少需要一个 BLOB 列")

    obj_type = normalize_object_type(object_type) if object_type else None
    if obj_type is None and conn.vendor == "mysql":
        obj_type = detect_mysql_object_type(conn, database=database, object_name=object_name)
    elif obj_type is None:
        obj_type = OBJECT_TYPE_TABLE

    lookup = resolve_path_lookup_table(
        conn,
        database=database,
        object_name=object_name,
        object_type=obj_type,
        manual=path_lookup_table,
    )
    return {
        "source_object_type": obj_type,
        "path_lookup_table": lookup,
        "blob_columns": cols,
        "blob_column": primary_blob_column(serialize_blob_columns(cols), cols[0]),
    }
