"""Navicat-style database catalog for BLOB migration and browse (PR1)."""
from __future__ import annotations

import logging
from typing import Any

from django.db import connections

from images.blob_migration_service import BLOB_TYPES_MYSQL, BlobMigrationError, validate_identifier
from images.blob_schema_helpers import OBJECT_TYPE_TABLE, OBJECT_TYPE_VIEW
from images.external_db_service import (
    ExternalDbError,
    db_alias_session,
    external_alias,
    list_database_aliases,
    parse_external_alias,
    validate_db_alias_reference,
)
from images.models import ExternalDbConnection

logger = logging.getLogger(__name__)

SYSTEM_DATABASES = frozenset(
    {"information_schema", "mysql", "performance_schema", "sys"}
)


class BlobCatalogError(Exception):
    pass


def _mysql_blob_types_sql() -> str:
    return ", ".join(f"'{value}'" for value in sorted(BLOB_TYPES_MYSQL))


def list_catalog_connections() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in list_database_aliases():
        payload = dict(entry)
        payload["connection_id"] = entry.get("connection_id")
        payload["migration_database"] = entry.get("name") or ""
        items.append(payload)
    return items


def _resolve_catalog_target(
    *,
    connection_id: int | None = None,
    db_alias: str | None = None,
) -> tuple[str, int | None, str]:
    if connection_id is not None:
        try:
            record = ExternalDbConnection.objects.get(pk=connection_id, enabled=1)
        except ExternalDbConnection.DoesNotExist as exc:
            raise BlobCatalogError(f"外部库连接不存在或已禁用: id={connection_id}") from exc
        alias = external_alias(record.id)
        return alias, record.id, record.db_name

    alias = validate_db_alias_reference(db_alias or "default")
    ext_id = parse_external_alias(alias)
    migration_db = ""
    if ext_id is not None:
        record = ExternalDbConnection.objects.get(pk=ext_id, enabled=1)
        migration_db = record.db_name
    else:
        cfg = connections[alias].settings_dict
        migration_db = str(cfg.get("NAME") or "")
    return alias, ext_id, migration_db


def list_connection_databases(
    *,
    connection_id: int | None = None,
    db_alias: str | None = None,
) -> list[dict[str, Any]]:
    alias, ext_id, migration_db = _resolve_catalog_target(connection_id=connection_id, db_alias=db_alias)

    with db_alias_session(alias) as session_alias:
        conn = connections[session_alias]
        if conn.vendor != "mysql":
            cfg = conn.settings_dict
            name = str(cfg.get("NAME") or migration_db or "")
            return [
                {
                    "name": name,
                    "is_migration_target": bool(name and name == migration_db),
                }
            ]

        with conn.cursor() as cursor:
            cursor.execute("SHOW DATABASES")
            rows = cursor.fetchall()

    databases: list[dict[str, Any]] = []
    for row in rows:
        name = str(row[0])
        if name in SYSTEM_DATABASES:
            continue
        databases.append(
            {
                "name": name,
                "is_migration_target": name == migration_db,
            }
        )
    databases.sort(key=lambda item: (not item["is_migration_target"], item["name"].lower()))
    return databases


def list_database_objects(
    database: str,
    *,
    connection_id: int | None = None,
    db_alias: str | None = None,
    object_type: str | None = None,
) -> dict[str, Any]:
    db_name = validate_identifier(database, label="数据库名")
    alias, ext_id, migration_db = _resolve_catalog_target(connection_id=connection_id, db_alias=db_alias)
    type_filter = (object_type or "").strip().lower()
    if type_filter in {"base table", "base_table"}:
        type_filter = OBJECT_TYPE_TABLE
    if type_filter in {"sql_view", "sql view"}:
        type_filter = OBJECT_TYPE_VIEW
    if type_filter and type_filter not in {OBJECT_TYPE_TABLE, OBJECT_TYPE_VIEW}:
        raise BlobCatalogError("object_type 无效，应为 table 或 view")

    with db_alias_session(alias, database=db_name) as session_alias:
        conn = connections[session_alias]
        if conn.vendor != "mysql":
            raise BlobCatalogError(f"暂不支持 {conn.vendor} 的目录浏览")

        blob_types = _mysql_blob_types_sql()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT TABLE_NAME, TABLE_TYPE
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_TYPE IN ('BASE TABLE', 'VIEW')
                ORDER BY TABLE_TYPE, TABLE_NAME
                """,
                [db_name],
            )
            table_rows = cursor.fetchall()

            cursor.execute(
                f"""
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND LOWER(DATA_TYPE) IN ({blob_types})
                ORDER BY TABLE_NAME, ORDINAL_POSITION
                """,
                [db_name],
            )
            blob_rows = cursor.fetchall()

    blob_by_table: dict[str, list[dict[str, Any]]] = {}
    for table_name, column_name, data_type in blob_rows:
        blob_by_table.setdefault(table_name, []).append(
            {
                "column": column_name,
                "data_type": (data_type or "").lower(),
            }
        )

    objects: list[dict[str, Any]] = []
    for table_name, table_type in table_rows:
        obj_type = OBJECT_TYPE_VIEW if table_type == "VIEW" else OBJECT_TYPE_TABLE
        if type_filter and obj_type != type_filter:
            continue
        objects.append(
            {
                "name": table_name,
                "object_type": obj_type,
                "blob_columns": blob_by_table.get(table_name, []),
            }
        )

    return {
        "connection_id": ext_id,
        "db_alias": alias,
        "database": db_name,
        "migration_database": migration_db,
        "is_migration_target": db_name == migration_db,
        "objects": objects,
    }


def get_database_object_detail(
    database: str,
    object_name: str,
    *,
    connection_id: int | None = None,
    db_alias: str | None = None,
) -> dict[str, Any]:
    db_name = validate_identifier(database, label="数据库名")
    table_name = validate_identifier(object_name, label="对象名")
    alias, ext_id, migration_db = _resolve_catalog_target(connection_id=connection_id, db_alias=db_alias)

    with db_alias_session(alias, database=db_name) as session_alias:
        conn = connections[session_alias]
        if conn.vendor != "mysql":
            raise BlobCatalogError(f"暂不支持 {conn.vendor} 的目录浏览")

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT TABLE_TYPE
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                LIMIT 1
                """,
                [db_name, table_name],
            )
            table_row = cursor.fetchone()
            if not table_row:
                raise BlobCatalogError(f"对象不存在: {db_name}.{table_name}")

            cursor.execute(
                """
                SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, EXTRA
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                [db_name, table_name],
            )
            column_rows = cursor.fetchall()

    table_type = table_row[0]
    obj_type = OBJECT_TYPE_VIEW if table_type == "VIEW" else OBJECT_TYPE_TABLE
    columns: list[dict[str, Any]] = []
    blob_columns: list[dict[str, Any]] = []
    for col_name, data_type, column_type, is_nullable, column_key, extra in column_rows:
        normalized_type = (data_type or "").lower()
        is_blob = normalized_type in BLOB_TYPES_MYSQL
        item = {
            "name": col_name,
            "data_type": normalized_type,
            "column_type": column_type,
            "is_nullable": is_nullable == "YES",
            "column_key": column_key or "",
            "extra": extra or "",
            "is_blob": is_blob,
        }
        columns.append(item)
        if is_blob:
            blob_columns.append({"column": col_name, "data_type": normalized_type})

    return {
        "connection_id": ext_id,
        "db_alias": alias,
        "database": db_name,
        "migration_database": migration_db,
        "is_migration_target": db_name == migration_db,
        "name": table_name,
        "object_type": obj_type,
        "columns": columns,
        "blob_columns": blob_columns,
    }
