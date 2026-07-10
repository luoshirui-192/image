"""Virtual read-only views over remote BLOB tables with local path substitution."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from django.db import connections
from django.utils import timezone

from images.blob_migration_service import (
    BLOB_TYPES_MYSQL,
    BlobMigrationError,
    _lookup_id_column,
    validate_identifier,
    validate_where_clause,
)
from images.blob_schema_helpers import (
    parse_blob_column_path_mappings,
    parse_blob_columns,
    serialize_blob_column_path_mappings,
    serialize_blob_columns,
)
from images.external_db_service import db_alias_session, validate_db_alias_reference
from images.models import BlobTableView, ImageInfo, ImageSourceMap

logger = logging.getLogger(__name__)

PATH_STATUS_PENDING = "pending"
PATH_STATUS_MIGRATED = "migrated"
PATH_STATUS_DELETED = "deleted"
PATH_STATUS_NO_DATA = "no_data"

_BLOB_PRESENCE_BATCH_SIZE = 200

DEFAULT_ROW_LIMIT = 100
MAX_ROW_LIMIT = 500


class BlobTableViewError(Exception):
    pass


@dataclass
class VirtualColumn:
    name: str
    data_type: str
    is_blob: bool = False
    is_path_substitute: bool = False


def _quote_ident(name: str) -> str:
    return f"`{validate_identifier(name)}`"


def validate_db_alias(alias: str) -> str:
    try:
        return validate_db_alias_reference(alias)
    except Exception as exc:
        raise BlobTableViewError(str(exc)) from exc



def _view_database_name(view: BlobTableView) -> str | None:
    value = (getattr(view, "database_name", "") or "").strip()
    return value or None


def _view_db_session(view: BlobTableView):
    return db_alias_session(view.db_alias, database=_view_database_name(view))


def _parse_display_columns(raw: str) -> list[str]:
    value = (raw or "").strip()
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise BlobTableViewError("display_columns 必须是 JSON 数组") from exc
    if not isinstance(parsed, list):
        raise BlobTableViewError("display_columns 必须是 JSON 数组")
    cols: list[str] = []
    for item in parsed:
        if not isinstance(item, str) or not item.strip():
            raise BlobTableViewError("display_columns 元素必须是非空字符串")
        cols.append(validate_identifier(item.strip(), label="列名"))
    return cols


def _serialize_display_columns(cols: list[str] | None) -> str:
    if not cols:
        return ""
    return json.dumps(cols, ensure_ascii=False)


def _load_view(view_id: int) -> BlobTableView:
    try:
        return BlobTableView.objects.get(pk=view_id)
    except BlobTableView.DoesNotExist as exc:
        raise BlobTableViewError("表视图不存在") from exc


def _fetch_remote_columns(conn, table: str) -> list[VirtualColumn]:
    table = validate_identifier(table, label="源表名")
    if conn.vendor == "mysql":
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                [table],
            )
            rows = cursor.fetchall()
        if not rows:
            raise BlobTableViewError(f"源表不存在或不可访问: {table}")
        return [
            VirtualColumn(
                name=col_name,
                data_type=(data_type or "").lower(),
                is_blob=(data_type or "").lower() in BLOB_TYPES_MYSQL,
            )
            for col_name, data_type, _ in rows
        ]

    if conn.vendor == "sqlite":
        with conn.cursor() as cursor:
            description = conn.introspection.get_table_description(cursor, table)
        if not description:
            raise BlobTableViewError(f"源表不存在或不可访问: {table}")
        cols: list[VirtualColumn] = []
        for col in description:
            col_type = (getattr(col, "type_code", "") or "").upper()
            cols.append(
                VirtualColumn(
                    name=col.name,
                    data_type=col_type.lower(),
                    is_blob="BLOB" in col_type,
                )
            )
        return cols

    raise BlobTableViewError(f"暂不支持 {conn.vendor} 的表视图")


def _view_blob_columns(view: BlobTableView) -> list[str]:
    cols = parse_blob_columns(view.blob_columns, view.blob_column)
    if not cols:
        raise BlobTableViewError("至少需要一个 BLOB 列")
    return [validate_identifier(col, label="BLOB 列") for col in cols]


def _path_lookup_table(view: BlobTableView) -> str:
    manual = (view.path_lookup_table or "").strip()
    if manual:
        return manual
    return view.source_table


def _resolve_display_columns(view: BlobTableView, remote_cols: list[VirtualColumn]) -> list[VirtualColumn]:
    blob_cols = _view_blob_columns(view)
    pk_col = validate_identifier(view.source_pk_column, label="主键列")
    col_map = {c.name: c for c in remote_cols}

    for blob_col in blob_cols:
        if blob_col not in col_map:
            raise BlobTableViewError(f"源对象缺少 BLOB 列: {blob_col}")
    if pk_col not in col_map:
        raise BlobTableViewError(f"源对象缺少主键列: {pk_col}")

    requested = _parse_display_columns(view.display_columns)
    if requested:
        for name in requested:
            if name not in col_map:
                raise BlobTableViewError(f"源对象缺少列: {name}")
        selected = [col_map[name] for name in requested if name not in blob_cols]
    else:
        selected = [c for c in remote_cols if c.name not in blob_cols]

    result: list[VirtualColumn] = []
    pk_added = False
    for col in selected:
        if col.is_blob:
            continue
        if col.name == pk_col:
            pk_added = True
        result.append(col)

    if not pk_added:
        result.insert(0, col_map[pk_col])

    for blob_col in blob_cols:
        result.append(
            VirtualColumn(
                name=blob_col,
                data_type="path",
                is_blob=False,
                is_path_substitute=True,
            )
        )
    return result


def get_view_schema(view_id: int) -> dict:
    view = _load_view(view_id)
    validate_db_alias(view.db_alias)
    with _view_db_session(view) as alias:
        conn = connections[alias]
        remote_cols = _fetch_remote_columns(conn, view.source_table)
        display_cols = _resolve_display_columns(view, remote_cols)
    return {
        "view_id": view.id,
        "source_table": view.source_table,
        "source_pk_column": view.source_pk_column,
        "blob_column": view.blob_column,
        "blob_columns": _view_blob_columns(view),
        "blob_column_path_mappings": parse_blob_column_path_mappings(view.blob_column_path_mappings),
        "columns": [
            {
                "name": col.name,
                "data_type": col.data_type,
                "is_path_substitute": col.is_path_substitute,
            }
            for col in display_cols
        ],
    }


def preview_table_schema(
    *,
    db_alias: str,
    source_table: str,
    source_pk_column: str,
    blob_column: str,
    display_columns: list[str] | None = None,
) -> dict:
    validate_db_alias(db_alias)
    table = validate_identifier(source_table, label="源表名")
    pk = validate_identifier(source_pk_column, label="主键列")
    blob = validate_identifier(blob_column, label="BLOB 列")

    temp = BlobTableView(
        source_table=table,
        source_pk_column=pk,
        blob_column=blob,
        display_columns=_serialize_display_columns(display_columns),
    )
    with db_alias_session(db_alias) as alias:
        conn = connections[alias]
        remote_cols = _fetch_remote_columns(conn, table)
        display_cols = _resolve_display_columns(temp, remote_cols)
    return {
        "source_table": table,
        "source_pk_column": pk,
        "blob_column": blob,
        "columns": [
            {
                "name": col.name,
                "data_type": col.data_type,
                "is_path_substitute": col.is_path_substitute,
            }
            for col in display_cols
        ],
    }


def count_view_rows(view_id: int) -> int:
    view = _load_view(view_id)
    where_sql, where_params = _build_where(view)
    validate_db_alias(view.db_alias)
    table = _quote_ident(view.source_table)
    with _view_db_session(view) as alias:
        conn = connections[alias]
        sql = f"SELECT COUNT(*) FROM {table}{where_sql}"
        with conn.cursor() as cursor:
            cursor.execute(sql, where_params)
            row = cursor.fetchone()
    return int(row[0]) if row else 0


def _build_where(view: BlobTableView) -> tuple[str, list[Any]]:
    clause = validate_where_clause(view.where_clause)
    if clause:
        return f" WHERE {clause}", []
    return "", []


def _serialize_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<binary {len(value)} bytes>"
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def _blob_nonempty_sql(conn, blob_quoted: str) -> str:
    return f"({blob_quoted} IS NOT NULL AND LENGTH({blob_quoted}) > 0)"


def _batch_ids_with_nonempty_blob(
    conn,
    *,
    lookup_table: str,
    lookup_id_column: str,
    blob_column: str,
    lookup_ids: list[str],
) -> set[str]:
    if not lookup_ids:
        return set()
    table = _quote_ident(lookup_table)
    id_col = _quote_ident(lookup_id_column)
    blob_col = _quote_ident(blob_column)
    nonempty = _blob_nonempty_sql(conn, blob_col)
    present: set[str] = set()
    for start in range(0, len(lookup_ids), _BLOB_PRESENCE_BATCH_SIZE):
        chunk = lookup_ids[start : start + _BLOB_PRESENCE_BATCH_SIZE]
        placeholders = ", ".join(["%s"] * len(chunk))
        sql = f"SELECT {id_col} FROM {table} WHERE {id_col} IN ({placeholders}) AND {nonempty}"
        with conn.cursor() as cursor:
            cursor.execute(sql, chunk)
            for row in cursor.fetchall():
                present.add(str(row[0]))
    return present


def _compute_blob_presence_for_page(
    conn,
    *,
    raw_rows: list[tuple],
    col_names: list[str],
    blob_cols: list[str],
    path_mappings: list[dict[str, str]] | None,
    pk_column: str,
    source_table: str,
) -> list[dict[str, bool]]:
    """Return per-row flags indicating whether each BLOB column has bytes to migrate."""
    presence = [{col: False for col in blob_cols} for _ in raw_rows]
    if not raw_rows:
        return presence

    if path_mappings:
        mapping_by_view_col = {m["view_column"]: m for m in path_mappings}
        for blob_col in blob_cols:
            mapping = mapping_by_view_col.get(blob_col)
            if not mapping:
                continue
            sid_col = mapping["source_id_column"]
            if sid_col not in col_names:
                continue
            sid_idx = col_names.index(sid_col)
            lookup_table = mapping["lookup_table"]
            lookup_id_col = _lookup_id_column(mapping)
            source_blob_col = (mapping.get("source_column") or blob_col).strip()

            ids_to_check: list[str] = []
            row_indices: list[int] = []
            for row_idx, raw in enumerate(raw_rows):
                sid_val = raw[sid_idx]
                if sid_val is None:
                    continue
                ids_to_check.append(str(sid_val))
                row_indices.append(row_idx)

            if not ids_to_check:
                continue
            present = _batch_ids_with_nonempty_blob(
                conn,
                lookup_table=lookup_table,
                lookup_id_column=lookup_id_col,
                blob_column=source_blob_col,
                lookup_ids=ids_to_check,
            )
            for row_idx, sid in zip(row_indices, ids_to_check):
                presence[row_idx][blob_col] = sid in present
        return presence

    pk = validate_identifier(pk_column, label="主键列")
    pks = [str(raw[col_names.index(pk)]) for raw in raw_rows]
    for blob_col in blob_cols:
        present = _batch_ids_with_nonempty_blob(
            conn,
            lookup_table=source_table,
            lookup_id_column=pk,
            blob_column=blob_col,
            lookup_ids=pks,
        )
        for row_idx, pk_val in enumerate(pks):
            presence[row_idx][blob_col] = pk_val in present
    return presence


def _build_path_cell(
    *,
    source_table: str,
    source_id: str,
    path_map: dict[str, dict],
    blob_column: str,
    source_column: str | None = None,
    has_blob_data: bool = True,
) -> dict:
    lookup_key = source_column or blob_column
    meta = path_map.get(lookup_key) or path_map.get(blob_column) or path_map.get("")
    if not meta:
        if not has_blob_data:
            return {
                "display": "无数据",
                "path": "",
                "image_info_id": None,
                "status": PATH_STATUS_NO_DATA,
            }
        return {
            "display": "未迁移",
            "path": "",
            "image_info_id": None,
            "status": PATH_STATUS_PENDING,
        }
    if meta["status"] == PATH_STATUS_DELETED:
        return {
            "display": "已删除",
            "path": "",
            "image_info_id": meta.get("image_info_id"),
            "status": PATH_STATUS_DELETED,
        }
    path = meta.get("path") or ""
    return {
        "display": path or "未迁移",
        "path": path,
        "image_info_id": meta.get("image_info_id"),
        "status": PATH_STATUS_MIGRATED,
    }


def _load_path_map(
    source_table: str,
    source_ids: list[str],
    *,
    blob_columns: list[str] | None = None,
    path_lookup_table: str | None = None,
) -> dict[str, dict[str, dict]]:
    if not source_ids:
        return {}
    lookup_table = (path_lookup_table or source_table).strip() or source_table
    mappings = ImageSourceMap.objects.filter(
        source_table=lookup_table,
        source_id__in=source_ids,
    )
    if blob_columns:
        legacy_cols = list(blob_columns)
        if len(legacy_cols) == 1:
            mappings = mappings.filter(source_column__in=[*legacy_cols, ""])
        else:
            mappings = mappings.filter(source_column__in=legacy_cols)
    image_ids = [m.image_info_id for m in mappings]
    images = {
        img.id: img
        for img in ImageInfo.objects.filter(id__in=image_ids)
    }
    result: dict[str, dict[str, dict]] = {}
    for mapping in mappings:
        column_key = mapping.source_column or (blob_columns[0] if blob_columns else "")
        image = images.get(mapping.image_info_id)
        if image is None or image.is_delete:
            meta = {
                "image_info_id": mapping.image_info_id,
                "path": "",
                "status": PATH_STATUS_DELETED,
            }
        else:
            meta = {
                "image_info_id": image.id,
                "path": image.image_path,
                "status": PATH_STATUS_MIGRATED,
            }
        result.setdefault(mapping.source_id, {})[column_key] = meta
    return result


def _load_path_maps_for_mappings(
    *,
    raw_rows: list[tuple],
    col_names: list[str],
    mappings: list[dict[str, str]],
    blob_cols: list[str],
    fallback_source_table: str,
    fallback_lookup_table: str,
) -> list[dict[str, dict[str, dict]]]:
    """Return per-row path maps keyed by view BLOB column name."""
    if not mappings:
        return []

    path_cache: dict[tuple[str, str], dict[str, dict[str, dict]]] = {}
    for mapping in mappings:
        view_col = mapping["view_column"]
        if view_col not in blob_cols:
            continue
        sid_col = mapping["source_id_column"]
        if sid_col not in col_names:
            continue
        sid_idx = col_names.index(sid_col)
        source_ids = list({str(row[sid_idx]) for row in raw_rows})
        cache_key = (mapping["lookup_table"], mapping["source_column"])
        if cache_key not in path_cache:
            path_cache[cache_key] = _load_path_map(
                fallback_source_table,
                source_ids,
                blob_columns=[mapping["source_column"]],
                path_lookup_table=mapping["lookup_table"],
            )
        else:
            existing = path_cache[cache_key]
            missing = [sid for sid in source_ids if sid not in existing]
            if missing:
                extra = _load_path_map(
                    fallback_source_table,
                    missing,
                    blob_columns=[mapping["source_column"]],
                    path_lookup_table=mapping["lookup_table"],
                )
                for sid, cols in extra.items():
                    existing.setdefault(sid, {}).update(cols)

    mapping_by_view_col = {m["view_column"]: m for m in mappings}
    row_maps: list[dict[str, dict[str, dict]]] = []
    for raw in raw_rows:
        row_paths: dict[str, dict[str, dict]] = {}
        for blob_col in blob_cols:
            mapping = mapping_by_view_col.get(blob_col)
            if not mapping:
                continue
            sid_col = mapping["source_id_column"]
            sid_idx = col_names.index(sid_col)
            source_id = str(raw[sid_idx])
            cache_key = (mapping["lookup_table"], mapping["source_column"])
            inner = path_cache.get(cache_key, {}).get(source_id, {})
            row_paths[blob_col] = inner
        row_maps.append(row_paths)
    return row_maps


def fetch_view_rows(
    view_id: int,
    *,
    offset: int = 0,
    limit: int = DEFAULT_ROW_LIMIT,
) -> dict:
    view = _load_view(view_id)
    if offset < 0:
        raise BlobTableViewError("offset 不能为负数")
    limit = min(max(1, limit), MAX_ROW_LIMIT)

    validate_db_alias(view.db_alias)
    pk = validate_identifier(view.source_pk_column, label="主键列")
    blob_cols = _view_blob_columns(view)
    table = _quote_ident(view.source_table)
    where_sql, where_params = _build_where(view)

    with _view_db_session(view) as alias:
        conn = connections[alias]
        remote_cols = _fetch_remote_columns(conn, view.source_table)
        display_cols = _resolve_display_columns(view, remote_cols)
        select_names = [c.name for c in display_cols if not c.is_path_substitute]
        select_sql = ", ".join(_quote_ident(name) for name in select_names)
        order_sql = _quote_ident(pk)
        sql = (
            f"SELECT {select_sql} FROM {table}{where_sql} "
            f"ORDER BY {order_sql} LIMIT %s OFFSET %s"
        )
        params = [*where_params, limit, offset]
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            raw_rows = cursor.fetchall()
            col_names = [col[0] for col in cursor.description]

        from images.blob_view_path_service import resolve_effective_path_mappings

        path_mappings = resolve_effective_path_mappings(view, conn, blob_cols)

        row_total = -1
        if offset == 0:
            count_sql = f"SELECT COUNT(*) FROM {table}{where_sql}"
            with conn.cursor() as cursor:
                cursor.execute(count_sql, where_params)
                count_row = cursor.fetchone()
            row_total = int(count_row[0]) if count_row else 0

        blob_presence = _compute_blob_presence_for_page(
            conn,
            raw_rows=raw_rows,
            col_names=col_names,
            blob_cols=blob_cols,
            path_mappings=path_mappings or None,
            pk_column=pk,
            source_table=view.source_table,
        )

    pk_index = col_names.index(pk) if pk in col_names else 0
    per_row_path_maps: list[dict[str, dict[str, dict]]] | None = None
    legacy_path_map: dict[str, dict[str, dict]] = {}
    if path_mappings:
        per_row_path_maps = _load_path_maps_for_mappings(
            raw_rows=raw_rows,
            col_names=col_names,
            mappings=path_mappings,
            blob_cols=blob_cols,
            fallback_source_table=view.source_table,
            fallback_lookup_table=_path_lookup_table(view),
        )
    else:
        source_ids = [str(row[pk_index]) for row in raw_rows]
        legacy_path_map = _load_path_map(
            view.source_table,
            source_ids,
            blob_columns=blob_cols,
            path_lookup_table=_path_lookup_table(view),
        )

    rows: list[dict] = []
    for row_idx, raw in enumerate(raw_rows):
        item: dict[str, Any] = {}
        source_id = str(raw[pk_index])
        for idx, name in enumerate(col_names):
            item[name] = _serialize_cell(raw[idx])
        if per_row_path_maps is not None:
            row_paths = per_row_path_maps[row_idx]
            for blob_col in blob_cols:
                mapping = next((m for m in path_mappings if m["view_column"] == blob_col), None)
                item[blob_col] = _build_path_cell(
                    source_table=view.source_table,
                    source_id=source_id,
                    path_map=row_paths.get(blob_col, {}),
                    blob_column=blob_col,
                    source_column=mapping["source_column"] if mapping else None,
                    has_blob_data=blob_presence[row_idx].get(blob_col, False),
                )
        else:
            row_paths = legacy_path_map.get(source_id, {})
            for blob_col in blob_cols:
                item[blob_col] = _build_path_cell(
                    source_table=view.source_table,
                    source_id=source_id,
                    path_map=row_paths,
                    blob_column=blob_col,
                    has_blob_data=blob_presence[row_idx].get(blob_col, False),
                )
        rows.append(item)

    # COUNT only on the first page (offset=0) so UI can show "loaded / total" without
    # scanning on every infinite-scroll append.
    total = row_total if offset == 0 else -1
    has_more = len(rows) >= limit if total < 0 else (offset + len(rows)) < total
    BlobTableView.objects.filter(pk=view.id).update(last_viewed_at=timezone.now())

    return {
        "view_id": view.id,
        "columns": [
            {
                "name": col.name,
                "data_type": col.data_type,
                "is_path_substitute": col.is_path_substitute,
            }
            for col in display_cols
        ],
        "rows": rows,
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": has_more,
    }


def create_table_view(
    *,
    name: str,
    db_alias: str,
    source_table: str,
    source_pk_column: str,
    blob_column: str = "",
    blob_columns: list[str] | None = None,
    source_object_type: str | None = None,
    path_lookup_table: str | None = None,
    database_name: str | None = None,
    display_columns: list[str] | None = None,
    where_clause: str = "",
    remark: str = "",
) -> BlobTableView:
    from images.blob_view_path_service import BlobViewPathError, resolve_source_metadata

    validate_db_alias(db_alias)
    table = validate_identifier(source_table, label="源表名")
    pk = validate_identifier(source_pk_column, label="主键列")
    where = validate_where_clause(where_clause)
    display_json = _serialize_display_columns(display_columns)

    initial_db = (database_name or "").strip()
    with db_alias_session(db_alias, database=initial_db or None) as alias:
        conn = connections[alias]
        db_name = initial_db or str(conn.settings_dict.get("NAME") or "").strip()
        try:
            meta = resolve_source_metadata(
                conn,
                database=db_name,
                object_name=table,
                object_type=source_object_type,
                path_lookup_table=path_lookup_table,
                blob_columns=blob_columns,
                blob_column=blob_column or None,
            )
        except BlobViewPathError as exc:
            raise BlobTableViewError(str(exc)) from exc

        remote_cols = _fetch_remote_columns(conn, table)
        temp = BlobTableView(
            source_table=table,
            source_pk_column=pk,
            blob_column=meta["blob_column"],
            blob_columns=serialize_blob_columns(meta["blob_columns"]),
            display_columns=display_json,
            where_clause=where,
        )
        _resolve_display_columns(temp, remote_cols)

    now = timezone.now()
    return BlobTableView.objects.create(
        name=(name or "").strip() or f"{table} 浏览",
        db_alias=db_alias,
        database_name=db_name,
        source_table=table,
        source_object_type=meta["source_object_type"],
        path_lookup_table=meta["path_lookup_table"],
        blob_column_path_mappings=serialize_blob_column_path_mappings(
            meta.get("blob_column_path_mappings") or []
        ),
        source_pk_column=pk,
        blob_column=meta["blob_column"],
        blob_columns=serialize_blob_columns(meta["blob_columns"]),
        display_columns=display_json,
        where_clause=where,
        remark=(remark or "").strip(),
        create_time=now,
        update_time=now,
    )


def update_table_view(view_id: int, **fields) -> BlobTableView:
    view = _load_view(view_id)
    name = fields.get("name")
    if name is not None:
        view.name = (name or "").strip() or view.name
    if "remark" in fields:
        view.remark = (fields.get("remark") or "").strip()
    if "where_clause" in fields:
        view.where_clause = validate_where_clause(fields.get("where_clause") or "")
    if "display_columns" in fields:
        view.display_columns = _serialize_display_columns(fields.get("display_columns"))
    if any(k in fields for k in ("db_alias", "source_table", "source_pk_column", "blob_column")):
        raise BlobTableViewError("源表与连接配置创建后不可修改，请删除后重建")

    validate_db_alias(view.db_alias)
    with _view_db_session(view) as alias:
        conn = connections[alias]
        remote_cols = _fetch_remote_columns(conn, view.source_table)
        _resolve_display_columns(view, remote_cols)

    view.update_time = timezone.now()
    view.save()
    return view


def delete_table_view(view_id: int) -> None:
    view = _load_view(view_id)
    view.delete()
