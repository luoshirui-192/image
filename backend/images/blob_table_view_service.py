"""Virtual read-only views over remote BLOB tables with local path substitution."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from django.db import connections
from django.db.utils import DatabaseError
from django.utils import timezone

from images.blob_migration_service import (
    BLOB_TYPES_MYSQL,
    BlobMigrationError,
    _lookup_id_column,
    validate_identifier,
    validate_where_clause,
)
from images.blob_schema_helpers import (
    OBJECT_TYPE_TABLE,
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
    return [validate_identifier(col, label="BLOB 列") for col in cols]


def infer_pk_column_from_detail(columns: list[dict]) -> str:
    """Pick PK column, else ``id``, else the first column."""
    for col in columns:
        if (col.get("column_key") or "") == "PRI":
            return validate_identifier(str(col["name"]), label="主键列")
    for col in columns:
        if str(col.get("name") or "").lower() == "id":
            return validate_identifier(str(col["name"]), label="主键列")
    if not columns:
        raise BlobTableViewError("源对象没有可用列")
    return validate_identifier(str(columns[0]["name"]), label="主键列")


def _effective_pk_column(view: BlobTableView, remote_cols: list[VirtualColumn]) -> str:
    col_map = {c.name: c for c in remote_cols}
    pk = (view.source_pk_column or "").strip()
    if pk and pk in col_map:
        return validate_identifier(pk, label="主键列")
    if remote_cols:
        return validate_identifier(remote_cols[0].name, label="主键列")
    raise BlobTableViewError("源对象没有可用列")


def _path_lookup_table(view: BlobTableView) -> str:
    manual = (view.path_lookup_table or "").strip()
    if manual:
        return manual
    return view.source_table


def _resolve_display_columns(view: BlobTableView, remote_cols: list[VirtualColumn]) -> list[VirtualColumn]:
    blob_cols = _view_blob_columns(view)
    pk_col = _effective_pk_column(view, remote_cols)
    col_map = {c.name: c for c in remote_cols}

    for blob_col in blob_cols:
        if blob_col not in col_map:
            raise BlobTableViewError(f"源对象缺少 BLOB 列: {blob_col}")

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


def _build_where(view: BlobTableView, extra_where: str = "") -> tuple[str, list[Any]]:
    parts: list[str] = []
    clause = validate_where_clause(view.where_clause)
    if clause:
        parts.append(f"({clause})")
    extra = validate_where_clause(extra_where)
    if extra:
        parts.append(f"({extra})")
    if parts:
        return f" WHERE {' AND '.join(parts)}", []
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
) -> tuple[set[str], bool]:
    """Return (ids with non-empty blob, check_succeeded)."""
    if not lookup_ids:
        return set(), True
    table = _quote_ident(lookup_table)
    id_col = _quote_ident(lookup_id_column)
    blob_col = _quote_ident(blob_column)
    nonempty = _blob_nonempty_sql(conn, blob_col)
    present: set[str] = set()
    for start in range(0, len(lookup_ids), _BLOB_PRESENCE_BATCH_SIZE):
        chunk = lookup_ids[start : start + _BLOB_PRESENCE_BATCH_SIZE]
        placeholders = ", ".join(["%s"] * len(chunk))
        sql = f"SELECT {id_col} FROM {table} WHERE {id_col} IN ({placeholders}) AND {nonempty}"
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, chunk)
                for row in cursor.fetchall():
                    present.add(str(row[0]))
        except DatabaseError:
            logger.warning(
                "blob presence check failed table=%s id_col=%s blob_col=%s",
                lookup_table,
                lookup_id_column,
                blob_column,
                exc_info=True,
            )
            return set(), False
    return present, True


def _apply_presence_lookup_result(
    presence: list[dict[str, bool]],
    *,
    blob_col: str,
    row_indices: list[int],
    lookup_ids: list[str],
    present: set[str],
    check_ok: bool,
) -> None:
    """Mark blob presence; failed remote checks default to pending (not 无数据)."""
    if not check_ok:
        for row_idx in row_indices:
            presence[row_idx][blob_col] = True
        return
    for row_idx, sid in zip(row_indices, lookup_ids):
        presence[row_idx][blob_col] = sid in present


def _presence_via_pk_on_table(
    conn,
    *,
    presence: list[dict[str, bool]],
    raw_rows: list[tuple],
    col_names: list[str],
    blob_col: str,
    pk_column: str,
    pk_index: int,
    source_table: str,
    legacy_path_map: dict[str, dict[str, dict]] | None,
) -> None:
    """Fallback: check blob bytes on source_table using the view PK column."""
    ids_to_check: list[str] = []
    row_indices: list[int] = []
    path_map = legacy_path_map or {}
    for row_idx, raw in enumerate(raw_rows):
        pk_val = str(raw[pk_index])
        row_paths = path_map.get(pk_val, {})
        if _local_blob_mapping_exists(
            blob_col=blob_col,
            source_column=None,
            path_map=row_paths,
        ):
            presence[row_idx][blob_col] = True
            continue
        ids_to_check.append(pk_val)
        row_indices.append(row_idx)
    if not ids_to_check:
        return
    present, check_ok = _batch_ids_with_nonempty_blob(
        conn,
        lookup_table=source_table,
        lookup_id_column=pk_column,
        blob_column=blob_col,
        lookup_ids=ids_to_check,
    )
    _apply_presence_lookup_result(
        presence,
        blob_col=blob_col,
        row_indices=row_indices,
        lookup_ids=ids_to_check,
        present=present,
        check_ok=check_ok,
    )


def _path_mapping_key_columns(path_mappings: list[dict[str, str]] | None) -> set[str]:
    cols: set[str] = set()
    for mapping in path_mappings or []:
        sid_col = (mapping.get("source_id_column") or "").strip()
        if sid_col:
            cols.add(sid_col)
    return cols


def _augment_select_names(
    select_names: list[str],
    *,
    pk: str,
    path_mappings: list[dict[str, str]] | None,
    remote_col_names: set[str],
) -> list[str]:
    """Ensure PK and path-mapping key columns are always fetched."""
    names = list(select_names)
    seen = set(names)
    for required in [pk, *_path_mapping_key_columns(path_mappings)]:
        if required and required in remote_col_names and required not in seen:
            names.append(required)
            seen.add(required)
    return names


def _local_blob_mapping_exists(
    *,
    blob_col: str,
    source_column: str | None,
    path_map: dict[str, dict],
) -> bool:
    """True when image_source_map already has an entry for this row/column."""
    lookup_key = source_column or blob_col
    return bool(
        path_map.get(blob_col)
        or path_map.get(lookup_key)
        or path_map.get("")
    )


def _compute_blob_presence_for_page(
    conn,
    *,
    raw_rows: list[tuple],
    col_names: list[str],
    blob_cols: list[str],
    path_mappings: list[dict[str, str]] | None,
    pk_column: str,
    source_table: str,
    per_row_path_maps: list[dict[str, dict[str, dict]]] | None = None,
    legacy_path_map: dict[str, dict[str, dict]] | None = None,
    pk_index: int = 0,
) -> list[dict[str, bool]]:
    """Return per-row flags indicating whether each BLOB column has bytes to migrate."""
    presence = [{col: False for col in blob_cols} for _ in raw_rows]
    if not raw_rows:
        return presence

    if path_mappings:
        mapping_by_view_col = {m["view_column"]: m for m in path_mappings}
        pk = validate_identifier(pk_column, label="主键列")
        for blob_col in blob_cols:
            mapping = mapping_by_view_col.get(blob_col)
            if not mapping:
                continue
            sid_col = mapping["source_id_column"]
            if sid_col not in col_names:
                logger.warning(
                    "path mapping key column missing from SELECT: %s (blob=%s)",
                    sid_col,
                    blob_col,
                )
                _presence_via_pk_on_table(
                    conn,
                    presence=presence,
                    raw_rows=raw_rows,
                    col_names=col_names,
                    blob_col=blob_col,
                    pk_column=pk,
                    pk_index=pk_index,
                    source_table=source_table,
                    legacy_path_map=legacy_path_map,
                )
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
                if per_row_path_maps is not None:
                    inner = per_row_path_maps[row_idx].get(blob_col, {})
                    source_column = mapping.get("source_column") if mapping else None
                    if _local_blob_mapping_exists(
                        blob_col=blob_col,
                        source_column=source_column,
                        path_map=inner,
                    ):
                        presence[row_idx][blob_col] = True
                        continue
                ids_to_check.append(str(sid_val))
                row_indices.append(row_idx)

            if not ids_to_check:
                continue
            present, check_ok = _batch_ids_with_nonempty_blob(
                conn,
                lookup_table=lookup_table,
                lookup_id_column=lookup_id_col,
                blob_column=source_blob_col,
                lookup_ids=ids_to_check,
            )
            _apply_presence_lookup_result(
                presence,
                blob_col=blob_col,
                row_indices=row_indices,
                lookup_ids=ids_to_check,
                present=present,
                check_ok=check_ok,
            )
        return presence

    pk = validate_identifier(pk_column, label="主键列")
    path_map = legacy_path_map or {}
    for blob_col in blob_cols:
        ids_to_check: list[str] = []
        row_indices: list[int] = []
        for row_idx, raw in enumerate(raw_rows):
            pk_val = str(raw[pk_index])
            row_paths = path_map.get(pk_val, {})
            if _local_blob_mapping_exists(
                blob_col=blob_col,
                source_column=None,
                path_map=row_paths,
            ):
                presence[row_idx][blob_col] = True
                continue
            ids_to_check.append(pk_val)
            row_indices.append(row_idx)

        if not ids_to_check:
            continue
        present, check_ok = _batch_ids_with_nonempty_blob(
            conn,
            lookup_table=source_table,
            lookup_id_column=pk,
            blob_column=blob_col,
            lookup_ids=ids_to_check,
        )
        _apply_presence_lookup_result(
            presence,
            blob_col=blob_col,
            row_indices=row_indices,
            lookup_ids=ids_to_check,
            present=present,
            check_ok=check_ok,
        )
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


def _path_cell_from_stored_path(path_value: Any) -> dict:
    """Build a path cell from a varchar path column (path-export tables)."""
    path = str(path_value or "").strip()
    if not path:
        return {
            "display": "无数据",
            "path": "",
            "image_info_id": None,
            "status": PATH_STATUS_NO_DATA,
        }
    image = (
        ImageInfo.objects.filter(image_path=path, is_delete=0)
        .order_by("-id")
        .only("id", "image_path")
        .first()
    )
    if image is None:
        # Path string exists but image_info is gone / not found.
        return {
            "display": path,
            "path": path,
            "image_info_id": None,
            "status": PATH_STATUS_DELETED,
        }
    return {
        "display": path,
        "path": path,
        "image_info_id": image.id,
        "status": PATH_STATUS_MIGRATED,
    }


def _stored_path_blob_columns(
    remote_cols: list[VirtualColumn],
    blob_cols: list[str],
) -> set[str]:
    """BLOB config columns that are physically varchar/path (exported path tables)."""
    remote = {c.name: c for c in remote_cols}
    stored: set[str] = set()
    for name in blob_cols:
        col = remote.get(name)
        if col is not None and not col.is_blob:
            stored.add(name)
    return stored


def _merge_path_cell_prefer_preview(map_cell: dict, stored_cell: dict) -> dict:
    """Prefer map cell when it already has preview id; else use stored path cell."""
    if map_cell.get("image_info_id"):
        if not map_cell.get("path") and stored_cell.get("path"):
            return {**map_cell, "path": stored_cell["path"], "display": stored_cell["path"]}
        return map_cell
    if stored_cell.get("image_info_id") or stored_cell.get("path"):
        return stored_cell
    return map_cell


def _load_path_map(
    source_table: str,
    source_ids: list[str],
    *,
    blob_columns: list[str] | None = None,
    path_lookup_table: str | None = None,
    source_uid: str | None = None,
) -> dict[str, dict[str, dict]]:
    if not source_ids:
        return {}
    lookup_table = (path_lookup_table or source_table).strip() or source_table
    from images.source_map_service import map_queryset_for_uid

    mappings = map_queryset_for_uid(
        source_uid or "",
        lookup_tables=[lookup_table],
        source_ids=source_ids,
        columns=blob_columns,
    )
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


def _mapping_source_ids(
    *,
    raw_rows: list[tuple],
    col_names: list[str],
    sid_col: str,
    pk_index: int,
    blob_col: str,
) -> tuple[list[str], bool]:
    """Resolve source_id values for path-map lookup; fall back to PK when key column missing."""
    if sid_col in col_names:
        sid_idx = col_names.index(sid_col)
        return (
            list({str(row[sid_idx]) for row in raw_rows if row[sid_idx] is not None}),
            True,
        )
    logger.warning(
        "path mapping key column missing from SELECT: %s (blob=%s); using PK fallback",
        sid_col,
        blob_col,
    )
    return (
        list({str(row[pk_index]) for row in raw_rows}),
        False,
    )


def _load_path_maps_for_mappings(
    *,
    raw_rows: list[tuple],
    col_names: list[str],
    mappings: list[dict[str, str]],
    blob_cols: list[str],
    fallback_source_table: str,
    fallback_lookup_table: str,
    pk_index: int = 0,
    source_uid: str | None = None,
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
        source_ids, _ = _mapping_source_ids(
            raw_rows=raw_rows,
            col_names=col_names,
            sid_col=sid_col,
            pk_index=pk_index,
            blob_col=view_col,
        )
        if not source_ids:
            continue
        cache_key = (mapping["lookup_table"], mapping["source_column"])
        if cache_key not in path_cache:
            path_cache[cache_key] = _load_path_map(
                fallback_source_table,
                source_ids,
                blob_columns=[mapping["source_column"]],
                path_lookup_table=mapping["lookup_table"],
                source_uid=source_uid,
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
                    source_uid=source_uid,
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
            if sid_col in col_names:
                source_id = str(raw[col_names.index(sid_col)])
            else:
                source_id = str(raw[pk_index])
            cache_key = (mapping["lookup_table"], mapping["source_column"])
            inner = path_cache.get(cache_key, {}).get(source_id, {})
            row_paths[blob_col] = inner
        row_maps.append(row_paths)
    return row_maps


def fetch_simulated_table_rows(
    view: BlobTableView,
    *,
    offset: int = 0,
    limit: int = DEFAULT_ROW_LIMIT,
    extra_where: str = "",
    touch_last_viewed: bool = True,
    include_total: bool = True,
) -> dict:
    """Fetch paginated rows with BLOB columns replaced by path cells (no BLOB bytes)."""
    if offset < 0:
        raise BlobTableViewError("offset 不能为负数")
    limit = min(max(1, limit), MAX_ROW_LIMIT)

    validate_db_alias(view.db_alias)
    table = _quote_ident(view.source_table)
    where_sql, where_params = _build_where(view, extra_where)

    with _view_db_session(view) as alias:
        conn = connections[alias]
        remote_cols = _fetch_remote_columns(conn, view.source_table)
        pk = _effective_pk_column(view, remote_cols)
        blob_cols = _view_blob_columns(view)
        display_cols = _resolve_display_columns(view, remote_cols)
        from images.blob_view_path_service import resolve_effective_path_mappings

        path_mappings = resolve_effective_path_mappings(view, conn, blob_cols)
        remote_col_names = {c.name for c in remote_cols}
        stored_path_cols = _stored_path_blob_columns(remote_cols, blob_cols)
        select_names = _augment_select_names(
            [c.name for c in display_cols if not c.is_path_substitute],
            pk=pk,
            path_mappings=path_mappings or None,
            remote_col_names=remote_col_names,
        )
        # Path-export tables store former BLOB values as varchar paths — fetch them.
        for col_name in stored_path_cols:
            if col_name in remote_col_names and col_name not in select_names:
                select_names.append(col_name)
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

        row_total = -1
        if offset == 0 and include_total:
            count_sql = f"SELECT COUNT(*) FROM {table}{where_sql}"
            with conn.cursor() as cursor:
                cursor.execute(count_sql, where_params)
                count_row = cursor.fetchone()
            row_total = int(count_row[0]) if count_row else 0

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
                pk_index=pk_index,
                source_uid=getattr(view, "source_uid", "") or "",
            )
        else:
            source_ids = [str(row[pk_index]) for row in raw_rows]
            # Always look up maps via configured path_lookup_table (original source),
            # not the physical export table name.
            legacy_path_map = _load_path_map(
                _path_lookup_table(view),
                source_ids,
                blob_columns=blob_cols,
                path_lookup_table=_path_lookup_table(view),
                source_uid=getattr(view, "source_uid", "") or "",
            )

        blob_presence = _compute_blob_presence_for_page(
            conn,
            raw_rows=raw_rows,
            col_names=col_names,
            blob_cols=blob_cols,
            path_mappings=path_mappings or None,
            pk_column=pk,
            source_table=view.source_table,
            per_row_path_maps=per_row_path_maps,
            legacy_path_map=legacy_path_map,
            pk_index=pk_index,
        )
        # For path-export varchar columns, nonempty path string means "has data".
        for row_idx, raw in enumerate(raw_rows):
            for col_name in stored_path_cols:
                if col_name not in col_names:
                    continue
                raw_val = raw[col_names.index(col_name)]
                if str(raw_val or "").strip():
                    blob_presence[row_idx][col_name] = True

    pk_index = col_names.index(pk) if pk in col_names else 0

    rows: list[dict] = []
    for row_idx, raw in enumerate(raw_rows):
        item: dict[str, Any] = {}
        source_id = str(raw[pk_index])
        for idx, name in enumerate(col_names):
            if name in blob_cols:
                continue
            item[name] = _serialize_cell(raw[idx])
        if per_row_path_maps is not None:
            row_paths = per_row_path_maps[row_idx]
            for blob_col in blob_cols:
                mapping = next((m for m in path_mappings if m["view_column"] == blob_col), None)
                map_cell = _build_path_cell(
                    source_table=view.source_table,
                    source_id=source_id,
                    path_map=row_paths.get(blob_col, {}),
                    blob_column=blob_col,
                    source_column=mapping["source_column"] if mapping else None,
                    has_blob_data=blob_presence[row_idx].get(blob_col, False),
                )
                if blob_col in stored_path_cols and blob_col in col_names:
                    stored_cell = _path_cell_from_stored_path(raw[col_names.index(blob_col)])
                    item[blob_col] = _merge_path_cell_prefer_preview(map_cell, stored_cell)
                else:
                    item[blob_col] = map_cell
        else:
            row_paths = legacy_path_map.get(source_id, {})
            for blob_col in blob_cols:
                map_cell = _build_path_cell(
                    source_table=view.source_table,
                    source_id=source_id,
                    path_map=row_paths,
                    blob_column=blob_col,
                    has_blob_data=blob_presence[row_idx].get(blob_col, False),
                )
                if blob_col in stored_path_cols and blob_col in col_names:
                    stored_cell = _path_cell_from_stored_path(raw[col_names.index(blob_col)])
                    item[blob_col] = _merge_path_cell_prefer_preview(map_cell, stored_cell)
                else:
                    item[blob_col] = map_cell
        rows.append(item)

    # COUNT only on the first page (offset=0) so UI can show "loaded / total" without
    # scanning on every infinite-scroll append.
    total = row_total if offset == 0 else -1
    has_more = len(rows) >= limit if total < 0 else (offset + len(rows)) < total
    if touch_last_viewed and view.pk:
        BlobTableView.objects.filter(pk=view.id).update(last_viewed_at=timezone.now())

    return {
        "view_id": view.pk,
        "remote_sql": sql,
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


def fetch_view_rows(
    view_id: int,
    *,
    offset: int = 0,
    limit: int = DEFAULT_ROW_LIMIT,
    include_total: bool = True,
) -> dict:
    view = _load_view(view_id)
    return fetch_simulated_table_rows(
        view,
        offset=offset,
        limit=limit,
        include_total=include_total,
    )


def build_ephemeral_table_view(
    *,
    db_alias: str,
    database_name: str,
    source_table: str,
    blob_columns: list[str],
    source_pk_column: str = "id",
    source_object_type: str | None = None,
    path_lookup_table: str = "",
    blob_column_path_mappings: list[dict[str, str]] | str | None = None,
    where_clause: str = "",
) -> BlobTableView:
    """In-memory view config for catalog SQL simulation (not persisted)."""
    from images.blob_view_path_service import BlobViewPathError, resolve_source_metadata

    validate_db_alias(db_alias)
    table = validate_identifier(source_table, label="源表名")
    pk = validate_identifier(source_pk_column or "id", label="主键列")
    cols = [validate_identifier(c, label="BLOB 列") for c in blob_columns if (c or "").strip()]
    if not cols:
        raise BlobTableViewError("至少需要一个 BLOB 列")

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
                path_lookup_table=path_lookup_table or None,
                blob_columns=cols,
            )
        except BlobViewPathError as exc:
            raise BlobTableViewError(str(exc)) from exc

    mappings_raw = blob_column_path_mappings
    if isinstance(mappings_raw, list):
        mappings_serialized = serialize_blob_column_path_mappings(mappings_raw)
    elif isinstance(mappings_raw, str):
        mappings_serialized = mappings_raw
    else:
        mappings_serialized = serialize_blob_column_path_mappings(meta.get("blob_column_path_mappings") or [])

    return BlobTableView(
        name=f"{table} SQL",
        db_alias=db_alias,
        database_name=db_name,
        source_table=table,
        source_pk_column=pk,
        blob_column=meta["blob_column"],
        blob_columns=serialize_blob_columns(meta["blob_columns"]),
        source_object_type=meta["source_object_type"],
        path_lookup_table=meta.get("path_lookup_table") or "",
        blob_column_path_mappings=mappings_serialized,
        where_clause=validate_where_clause(where_clause),
        display_columns="",
    )


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
    from images.blob_migration_service import find_migration_source_match
    from images.source_identity import generate_source_uid, is_valid_source_uid, normalize_source_uid

    view_uid = ""
    matched_source, _ambiguous = find_migration_source_match(
        db_alias=db_alias,
        database=db_name,
        source_table=table,
        source_object_type=meta["source_object_type"],
    )
    if matched_source is not None:
        view_uid = normalize_source_uid(getattr(matched_source, "source_uid", ""))
    if not is_valid_source_uid(view_uid):
        view_uid = generate_source_uid()

    return BlobTableView.objects.create(
        name=(name or "").strip() or f"{table} 浏览",
        db_alias=db_alias,
        database_name=db_name,
        source_uid=view_uid,
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
    if "database_name" in fields:
        view.database_name = (fields.get("database_name") or "").strip()
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


def auto_provision_table_views_for_connection(record) -> dict[str, int | list[str]]:
    """Create saved table-view configs for every table/view on a new external connection."""
    from images.blob_catalog_service import BlobCatalogError, get_database_object_detail, list_database_objects
    from images.external_db_service import external_alias
    from images.models import ExternalDbConnection

    if not isinstance(record, ExternalDbConnection):
        raise BlobTableViewError("无效的外部库连接")

    db_alias = external_alias(record.id)
    database = (record.db_name or "").strip()
    if not database:
        return {"created": 0, "skipped": 0, "failed": 0, "errors": ["连接未配置数据库名"]}

    try:
        catalog = list_database_objects(database, db_alias=db_alias)
    except BlobCatalogError as exc:
        return {"created": 0, "skipped": 0, "failed": 0, "errors": [str(exc)]}

    created = 0
    skipped = 0
    failed = 0
    errors: list[str] = []

    for obj in catalog.get("objects") or []:
        obj_name = str(obj.get("name") or "").strip()
        obj_type = str(obj.get("object_type") or OBJECT_TYPE_TABLE).strip() or OBJECT_TYPE_TABLE
        if not obj_name:
            continue

        if BlobTableView.objects.filter(
            db_alias=db_alias,
            database_name=database,
            source_table=obj_name,
            source_object_type=obj_type,
        ).exists():
            skipped += 1
            continue

        try:
            detail = get_database_object_detail(database, obj_name, db_alias=db_alias)
            columns = detail.get("columns") or []
            pk = infer_pk_column_from_detail(columns)
            blob_cols = [
                str(item.get("column") or "").strip()
                for item in (detail.get("blob_columns") or [])
                if str(item.get("column") or "").strip()
            ]
            create_table_view(
                name=obj_name,
                db_alias=db_alias,
                database_name=database,
                source_table=obj_name,
                source_object_type=obj_type,
                source_pk_column=pk,
                blob_columns=blob_cols or None,
                blob_column=blob_cols[0] if blob_cols else "",
                remark="连接建立时自动生成",
            )
            created += 1
        except Exception as exc:
            failed += 1
            if len(errors) < 20:
                errors.append(f"{obj_name}: {exc}")

    return {
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
    }
