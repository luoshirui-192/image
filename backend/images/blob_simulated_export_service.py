"""Export simulated browse rows (BLOB → path strings) into another connection's table."""
from __future__ import annotations

import logging
from typing import Any

from django.db import connections
from django.utils import timezone

from images.blob_migration_service import BLOB_TYPES_MYSQL, validate_identifier
from images.blob_schema_helpers import parse_blob_columns
from images.blob_table_view_service import (
    MAX_ROW_LIMIT,
    BlobTableViewError,
    _load_view,
    _parse_display_columns,
    _quote_ident,
    _serialize_cell,
    create_table_view,
    fetch_simulated_table_rows,
    validate_db_alias,
)
from images.external_db_service import db_alias_session, external_alias, parse_external_alias
from images.models import BlobTableView, ExternalDbConnection

logger = logging.getLogger(__name__)

PATH_COLUMN_SQL = "varchar(500) NOT NULL DEFAULT ''"
IF_EXISTS_FAIL = "fail"
IF_EXISTS_REPLACE = "replace"
IF_EXISTS_TRUNCATE = "truncate"
IF_EXISTS_CHOICES = frozenset({IF_EXISTS_FAIL, IF_EXISTS_REPLACE, IF_EXISTS_TRUNCATE})


class SimulatedExportError(Exception):
    pass


class SimulatedExportCancelled(SimulatedExportError):
    """Raised when an async export job is cancelled mid-run."""


class SimulatedExportPaused(SimulatedExportError):
    """Raised when an async export job is paused mid-run (keeps checkpoint)."""

    def __init__(self, message: str = "已暂停", *, offset: int = 0, rows_written: int = 0):
        super().__init__(message)
        self.offset = int(offset or 0)
        self.rows_written = int(rows_written or 0)


def _path_cell_to_string(value: Any) -> str:
    """Write real path only; pending / no_data / deleted become empty string."""
    if isinstance(value, dict):
        return str(value.get("path") or "")
    if value is None:
        return ""
    return str(value)


def _resolve_target_alias(
    *,
    target_db_alias: str | None = None,
    target_connection_id: int | None = None,
) -> str:
    if target_connection_id is not None:
        try:
            record = ExternalDbConnection.objects.get(pk=target_connection_id, enabled=1)
        except ExternalDbConnection.DoesNotExist as exc:
            raise SimulatedExportError(f"目标连接不存在或未启用: id={target_connection_id}") from exc
        return external_alias(record.id)

    alias = (target_db_alias or "").strip()
    if not alias:
        raise SimulatedExportError("请提供 target_connection_id 或 target_db_alias")
    try:
        return validate_db_alias(alias)
    except BlobTableViewError as exc:
        raise SimulatedExportError(str(exc)) from exc


def _fetch_source_column_defs(view) -> list[dict[str, Any]]:
    """Return ordered column defs from source: name, data_type, column_type, is_blob, is_nullable, column_key."""
    blob_cols = set(parse_blob_columns(view.blob_columns, view.blob_column))
    with db_alias_session(view.db_alias, database=(view.database_name or None) or None) as alias:
        conn = connections[alias]
        table = validate_identifier(view.source_table, label="源表名")
        if conn.vendor == "mysql":
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                    """,
                    [table],
                )
                rows = cursor.fetchall()
            if not rows:
                raise SimulatedExportError(f"源表不存在或不可访问: {table}")
            defs = []
            for name, data_type, column_type, is_nullable, column_key in rows:
                dtype = (data_type or "").lower()
                defs.append(
                    {
                        "name": name,
                        "data_type": dtype,
                        "column_type": column_type or dtype,
                        "is_blob": name in blob_cols or dtype in BLOB_TYPES_MYSQL,
                        "is_nullable": is_nullable == "YES",
                        "column_key": column_key or "",
                    }
                )
            return defs

        if conn.vendor == "sqlite":
            with conn.cursor() as cursor:
                description = conn.introspection.get_table_description(cursor, table)
            if not description:
                raise SimulatedExportError(f"源表不存在或不可访问: {table}")
            defs = []
            for col in description:
                col_type = (getattr(col, "type_code", "") or "TEXT").upper()
                name = col.name
                is_blob = name in blob_cols or "BLOB" in col_type
                defs.append(
                    {
                        "name": name,
                        "data_type": col_type.lower(),
                        "column_type": "BLOB" if is_blob else (col_type or "TEXT"),
                        "is_blob": is_blob,
                        "is_nullable": True,
                        "column_key": "",
                    }
                )
            return defs

    raise SimulatedExportError(f"暂不支持导出自 {getattr(conn, 'vendor', 'unknown')}")


def _target_column_sql(col: dict[str, Any]) -> str:
    name = _quote_ident(col["name"])
    if col["is_blob"] or col.get("is_path_substitute"):
        return f"{name} {PATH_COLUMN_SQL}"
    column_type = (col.get("column_type") or col.get("data_type") or "text").strip()
    # Strip auto_increment / on update extras for portability; keep nullability loosely.
    lower = column_type.lower()
    if "auto_increment" in lower:
        column_type = column_type.replace("auto_increment", "").replace("AUTO_INCREMENT", "").strip()
    nullable = "" if col.get("is_nullable", True) else " NOT NULL"
    return f"{name} {column_type}{nullable}"


def _build_create_table_sql(table: str, columns: list[dict[str, Any]], *, vendor: str) -> str:
    col_sql = ", ".join(_target_column_sql(c) for c in columns)
    pk_cols = [c["name"] for c in columns if (c.get("column_key") or "") == "PRI" and not c["is_blob"]]
    if pk_cols and vendor == "mysql":
        pk = ", ".join(_quote_ident(n) for n in pk_cols)
        col_sql = f"{col_sql}, PRIMARY KEY ({pk})"
    quoted = _quote_ident(table)
    if vendor == "mysql":
        return f"CREATE TABLE {quoted} ({col_sql}) ENGINE=InnoDB DEFAULT CHARSET=utf8"
    return f"CREATE TABLE {quoted} ({col_sql})"


def _table_exists(conn, table: str) -> bool:
    table = validate_identifier(table, label="目标表名")
    if conn.vendor == "mysql":
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1 FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                LIMIT 1
                """,
                [table],
            )
            return cursor.fetchone() is not None
    if conn.vendor == "sqlite":
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = %s LIMIT 1",
                [table],
            )
            return cursor.fetchone() is not None
    raise SimulatedExportError(f"暂不支持目标库类型 {conn.vendor}")


def _list_target_columns(conn, table: str) -> list[str]:
    table = validate_identifier(table, label="目标表名")
    if conn.vendor == "mysql":
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COLUMN_NAME FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                [table],
            )
            return [row[0] for row in cursor.fetchall()]
    if conn.vendor == "sqlite":
        with conn.cursor() as cursor:
            description = conn.introspection.get_table_description(cursor, table)
        return [col.name for col in description]
    raise SimulatedExportError(f"暂不支持目标库类型 {conn.vendor}")


def _prepare_target_table(
    conn,
    *,
    table: str,
    columns: list[dict[str, Any]],
    if_exists: str,
) -> None:
    exists = _table_exists(conn, table)
    quoted = _quote_ident(table)

    if if_exists == IF_EXISTS_FAIL:
        if exists:
            raise SimulatedExportError(f"目标表已存在: {table}（请选择替换或清空，或换表名）")
        with conn.cursor() as cursor:
            cursor.execute(_build_create_table_sql(table, columns, vendor=conn.vendor))
        return

    if if_exists == IF_EXISTS_REPLACE:
        with conn.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {quoted}")
            cursor.execute(_build_create_table_sql(table, columns, vendor=conn.vendor))
        return

    if if_exists == IF_EXISTS_TRUNCATE:
        if not exists:
            raise SimulatedExportError(f"目标表不存在，无法清空后写入: {table}")
        expected = [c["name"] for c in columns]
        actual = _list_target_columns(conn, table)
        if actual != expected:
            raise SimulatedExportError(
                f"目标表列与源不一致，无法 truncate。"
                f"目标={actual} 期望={expected}"
            )
        with conn.cursor() as cursor:
            if conn.vendor == "sqlite":
                cursor.execute(f"DELETE FROM {quoted}")
            else:
                cursor.execute(f"TRUNCATE TABLE {quoted}")
        return

    raise SimulatedExportError(f"不支持的 if_exists: {if_exists}")


def _flatten_row(row: dict, column_names: list[str], path_columns: set[str]) -> list[Any]:
    values: list[Any] = []
    for name in column_names:
        raw = row.get(name)
        if name in path_columns:
            values.append(_path_cell_to_string(raw))
        else:
            values.append(_serialize_cell(raw))
    return values


def _find_existing_target_view(
    *,
    target_alias: str,
    target_database: str,
    target_table: str,
) -> BlobTableView | None:
    qs = BlobTableView.objects.filter(db_alias=target_alias, source_table=target_table)
    db = (target_database or "").strip()
    if db:
        return qs.filter(database_name=db).first()
    return qs.filter(database_name=db).first() or qs.first()


def _ensure_target_browse_view(
    source_view: BlobTableView,
    *,
    target_alias: str,
    target_database: str,
    target_table: str,
    target_columns: list[str],
) -> dict[str, Any]:
    """Create or reuse a browse config for the exported path table.

    Keeps the same logical path mapping as the source view so image preview
    still resolves via image_source_map (原表与导出表都可浏览预览).
    """
    from images.blob_schema_helpers import parse_blob_columns, primary_blob_column, serialize_blob_columns

    remark = f"自 view#{source_view.id} {source_view.source_table} 导出"
    blob_cols = [
        c
        for c in parse_blob_columns(source_view.blob_columns, source_view.blob_column)
        if c in set(target_columns)
    ]
    path_lookup = (
        (source_view.path_lookup_table or "").strip()
        or (source_view.source_table or "").strip()
    )
    source_uid = (getattr(source_view, "source_uid", "") or "").strip()
    mappings_raw = getattr(source_view, "blob_column_path_mappings", "") or ""

    existing = _find_existing_target_view(
        target_alias=target_alias,
        target_database=target_database,
        target_table=target_table,
    )
    if existing is not None:
        updates: dict[str, Any] = {
            "remark": remark[:500],
            "update_time": timezone.now(),
        }
        if blob_cols:
            updates["blob_columns"] = serialize_blob_columns(blob_cols)
            updates["blob_column"] = primary_blob_column(None, blob_cols[0])
        if path_lookup:
            updates["path_lookup_table"] = path_lookup
        if source_uid:
            updates["source_uid"] = source_uid
        if mappings_raw:
            updates["blob_column_path_mappings"] = mappings_raw
        BlobTableView.objects.filter(pk=existing.pk).update(**updates)
        existing.refresh_from_db()
        return {
            "target_view_id": existing.id,
            "target_view_created": False,
            "target_view_name": existing.name,
        }

    col_set = set(target_columns)
    try:
        source_display = _parse_display_columns(source_view.display_columns)
    except BlobTableViewError:
        source_display = []
    display_cols = [c for c in source_display if c in col_set] or None

    created = create_table_view(
        name=f"{target_table}（路径导出）",
        db_alias=target_alias,
        database_name=target_database or None,
        source_table=target_table,
        source_object_type="table",
        source_pk_column=source_view.source_pk_column or "id",
        blob_column=blob_cols[0] if blob_cols else "",
        blob_columns=blob_cols or None,
        path_lookup_table=path_lookup or None,
        display_columns=display_cols,
        remark=remark,
        # Share path identity with the source browse view so both preview via image_source_map.
        source_uid=source_uid or None,
        blob_column_path_mappings=mappings_raw or None,
    )
    return {
        "target_view_id": created.id,
        "target_view_created": True,
        "target_view_name": created.name,
    }


def export_simulated_table_to_connection(
    view_id: int,
    *,
    target_db_alias: str | None = None,
    target_connection_id: int | None = None,
    target_database: str = "",
    target_table: str = "",
    if_exists: str = IF_EXISTS_FAIL,
    page_size: int | None = None,
    start_offset: int = 0,
    skip_prepare: bool = False,
    progress_callback=None,
    should_cancel=None,
    should_pause=None,
) -> dict[str, Any]:
    """Materialize path-substituted browse rows into a physical table on another connection.

    progress_callback(rows_written=..., total_estimate=..., offset=...) is optional for async jobs.
    should_cancel() / should_pause() stop the loop early.
    start_offset + skip_prepare resume after pause/restart without wiping the target table.
    """
    mode = (if_exists or IF_EXISTS_FAIL).strip().lower()
    if mode not in IF_EXISTS_CHOICES:
        raise SimulatedExportError(f"if_exists 必须是 {', '.join(sorted(IF_EXISTS_CHOICES))}")

    view = _load_view(view_id)
    validate_db_alias(view.db_alias)
    target_alias = _resolve_target_alias(
        target_db_alias=target_db_alias,
        target_connection_id=target_connection_id,
    )
    target_db = (target_database or "").strip()
    if not target_db and parse_external_alias(target_alias) is not None:
        # Fall back to connection's default database.
        ext_id = parse_external_alias(target_alias)
        record = ExternalDbConnection.objects.filter(pk=ext_id).first()
        target_db = (record.db_name if record else "") or ""

    dest_table = validate_identifier(
        (target_table or "").strip() or view.source_table,
        label="目标表名",
    )

    source_defs = _fetch_source_column_defs(view)
    # Only export display-relevant columns: non-blob from source + configured blob/path cols.
    blob_cols = parse_blob_columns(view.blob_columns, view.blob_column)
    blob_set = set(blob_cols)
    export_cols: list[dict[str, Any]] = []
    for col in source_defs:
        if col["name"] in blob_set or col["is_blob"]:
            if col["name"] in blob_set:
                export_cols.append({**col, "is_blob": True, "is_path_substitute": True})
            # Skip unconfigured blob columns.
            continue
        export_cols.append(col)
    for name in blob_cols:
        if not any(c["name"] == name for c in export_cols):
            export_cols.append(
                {
                    "name": name,
                    "data_type": "path",
                    "column_type": PATH_COLUMN_SQL,
                    "is_blob": True,
                    "is_path_substitute": True,
                    "is_nullable": False,
                    "column_key": "",
                }
            )

    if not export_cols:
        raise SimulatedExportError("没有可导出的列")

    column_names = [c["name"] for c in export_cols]
    path_columns = {c["name"] for c in export_cols if c.get("is_path_substitute") or c.get("is_blob")}
    batch = max(1, min(page_size or MAX_ROW_LIMIT, MAX_ROW_LIMIT))
    offset = max(0, int(start_offset or 0))
    rows_written = offset if skip_prepare else 0

    with db_alias_session(target_alias, database=target_db or None) as session_alias:
        conn = connections[session_alias]
        if skip_prepare:
            if not _table_exists(conn, dest_table):
                raise SimulatedExportError(
                    f"续传失败：目标表不存在 {dest_table}（请重新导出并选择替换/新建）"
                )
            expected = column_names
            actual = _list_target_columns(conn, dest_table)
            if actual != expected:
                raise SimulatedExportError(
                    f"续传失败：目标表列与源不一致。目标={actual} 期望={expected}"
                )
        else:
            _prepare_target_table(conn, table=dest_table, columns=export_cols, if_exists=mode)

        placeholders = ", ".join(["%s"] * len(column_names))
        col_list = ", ".join(_quote_ident(n) for n in column_names)
        insert_sql = f"INSERT INTO {_quote_ident(dest_table)} ({col_list}) VALUES ({placeholders})"

        total_estimate: int | None = None
        while True:
            if should_cancel and should_cancel():
                raise SimulatedExportCancelled("用户取消导出")
            if should_pause and should_pause():
                raise SimulatedExportPaused("用户暂停导出", offset=offset, rows_written=rows_written)
            page = fetch_simulated_table_rows(
                view,
                offset=offset,
                limit=batch,
                include_total=(offset == 0 or total_estimate is None),
                touch_last_viewed=False,
            )
            if total_estimate is None and page.get("total") is not None:
                try:
                    total_estimate = int(page.get("total") or 0)
                except (TypeError, ValueError):
                    total_estimate = None
                if progress_callback:
                    progress_callback(
                        rows_written=rows_written,
                        total_estimate=total_estimate,
                        offset=offset,
                    )
            rows = page.get("rows") or []
            if not rows:
                break
            values = [_flatten_row(row, column_names, path_columns) for row in rows]
            with conn.cursor() as cursor:
                cursor.executemany(insert_sql, values)
            rows_written += len(values)
            offset += len(rows)
            if progress_callback:
                progress_callback(
                    rows_written=rows_written,
                    total_estimate=total_estimate,
                    offset=offset,
                )
            if should_cancel and should_cancel():
                raise SimulatedExportCancelled("用户取消导出")
            if should_pause and should_pause():
                raise SimulatedExportPaused("用户暂停导出", offset=offset, rows_written=rows_written)
            if not page.get("has_more"):
                break

    result: dict[str, Any] = {
        "view_id": view.id,
        "source_table": view.source_table,
        "source_db_alias": view.db_alias,
        "source_database": view.database_name or "",
        "target_db_alias": target_alias,
        "target_database": target_db,
        "target_table": dest_table,
        "if_exists": mode,
        "rows_written": rows_written,
        "last_offset": offset,
        "columns": [
            {
                "name": c["name"],
                "is_path_substitute": bool(c.get("is_path_substitute") or c.get("is_blob")),
            }
            for c in export_cols
        ],
    }

    try:
        view_meta = _ensure_target_browse_view(
            view,
            target_alias=target_alias,
            target_database=target_db,
            target_table=dest_table,
            target_columns=column_names,
        )
        result.update(view_meta)
    except Exception as exc:
        logger.warning(
            "ensure target browse view failed after export view_id=%s target=%s.%s: %s",
            view.id,
            target_db,
            dest_table,
            exc,
            exc_info=True,
        )
        result["target_view_error"] = str(exc)[:500]

    return result
