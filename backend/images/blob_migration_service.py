"""Migrate image BLOB columns from legacy tables into upload/ + image_info."""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from django.conf import settings
from django.db import close_old_connections, connections
from django.utils import timezone

from images.blob_schema_helpers import (
    OBJECT_TYPE_VIEW,
    map_storage_table,
    normalize_object_type,
    parse_blob_column_path_mappings,
    parse_blob_columns,
    serialize_blob_column_path_mappings,
    serialize_blob_columns,
)
from images.external_db_service import (
    db_alias_session,
    list_database_aliases,
    validate_db_alias_reference,
)
from images.models import BlobMigrationJob, BlobMigrationJobError, BlobMigrationSource, ImageCategory, ImageInfo, ImageSourceMap
from images.services import DuplicateImageError, save_image_bytes_for_migration
from utils.file_security import detect_image_type, extension_from_filename, normalize_suffix

logger = logging.getLogger(__name__)

IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
FORBIDDEN_WHERE_RE = re.compile(
    r";|--|/\*|\*/|\b(DROP|DELETE|UPDATE|INSERT|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

BLOB_TYPES_MYSQL = frozenset({"blob", "tinyblob", "mediumblob", "longblob", "binary", "varbinary"})

# Short-lived cache for expensive remote COUNT scans (job polling / source list).
_STATS_CACHE: dict[tuple, tuple[float, dict]] = {}
_STATS_CACHE_TTL_SECONDS = 20.0
_STATS_CACHE_LOCK = Lock()


class BlobMigrationError(Exception):
    pass


@dataclass
class MigrationItemResult:
    source_id: str
    success: bool
    source_column: str = ""
    image_info_id: int | None = None
    filename: str = ""
    error: str = ""
    skipped: bool = False


@dataclass
class MigrationBatchResult:
    rows_fetched: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    last_pk: str = ""


@dataclass
class MigrationRunResult:
    source_id: int
    source_table: str
    dry_run: bool
    total_candidates: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    items: list[MigrationItemResult] = field(default_factory=list)


def _upload_workers() -> int:
    from django.db import connection

    if connection.vendor == "sqlite":
        return 1
    workers = int(getattr(settings, "BLOB_MIGRATION_UPLOAD_WORKERS", 2))
    return max(1, min(workers, 8))


def _max_batch_size(batch_size: int) -> int:
    cap = int(getattr(settings, "BLOB_MIGRATION_BATCH_MAX", 500))
    return max(1, min(int(batch_size), max(1, cap)))


def _job_cancelled(job_id: int) -> bool:
    return BlobMigrationJob.objects.filter(pk=job_id, cancel_requested=1).exists()


def _record_job_error(
    job_id: int,
    *,
    source_pk: str,
    source_column: str = "",
    filename: str,
    error: str,
) -> None:
    BlobMigrationJobError.objects.create(
        job_id=job_id,
        source_pk=source_pk[:128],
        source_column=(source_column or "")[:64],
        filename=(filename or "")[:255],
        error_message=(error or "")[:1000],
        create_time=timezone.now(),
    )


def _update_job_progress(job: BlobMigrationJob, batch: MigrationBatchResult, *, last_pk: str | None = None) -> None:
    updates = {
        "processed": job.processed + batch.processed,
        "succeeded": job.succeeded + batch.succeeded,
        "failed": job.failed + batch.failed,
        "skipped": job.skipped + batch.skipped,
        "updated_at": timezone.now(),
    }
    if last_pk is not None:
        updates["last_pk_cursor"] = last_pk[:128]
    BlobMigrationJob.objects.filter(pk=job.pk).update(**updates)
    for key, value in updates.items():
        setattr(job, key, value)


def validate_identifier(name: str, *, label: str = "标识符") -> str:
    value = (name or "").strip()
    if not value or not IDENTIFIER_RE.match(value):
        raise BlobMigrationError(f"{label}无效: {name!r}")
    return value


def validate_where_clause(clause: str) -> str:
    value = (clause or "").strip()
    if not value:
        return ""
    if FORBIDDEN_WHERE_RE.search(value):
        raise BlobMigrationError("where 条件包含不允许的关键字或符号")
    return value


def validate_db_alias(alias: str) -> str:
    try:
        return validate_db_alias_reference(alias)
    except Exception as exc:
        raise BlobMigrationError(str(exc)) from exc


def discover_blob_tables(*, db_alias: str = "default") -> list[dict]:
    """List tables/columns that may store binary image data."""
    validate_db_alias(db_alias)
    with db_alias_session(db_alias) as alias:
        conn = connections[alias]
        return _discover_blob_tables_on_connection(conn)


def _discover_blob_tables_on_connection(conn) -> list[dict]:
    if conn.vendor == "mysql":
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.TABLE_NAME, t.TABLE_TYPE, c.COLUMN_NAME, c.DATA_TYPE, c.CHARACTER_MAXIMUM_LENGTH
                FROM information_schema.COLUMNS c
                JOIN information_schema.TABLES t
                  ON t.TABLE_SCHEMA = c.TABLE_SCHEMA
                 AND t.TABLE_NAME = c.TABLE_NAME
                WHERE c.TABLE_SCHEMA = DATABASE()
                  AND c.DATA_TYPE IN ('blob', 'tinyblob', 'mediumblob', 'longblob', 'binary', 'varbinary')
                ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
                """
            )
            rows = cursor.fetchall()
        grouped: dict[str, dict] = {}
        for table_name, table_type, column_name, data_type, max_len in rows:
            entry = grouped.setdefault(
                table_name,
                {
                    "table": table_name,
                    "object_type": "view" if table_type == "VIEW" else "table",
                    "columns": [],
                },
            )
            entry["columns"].append(
                {
                    "column": column_name,
                    "data_type": data_type,
                    "max_length": max_len,
                }
            )
        return list(sorted(grouped.values(), key=lambda item: item["table"]))

    if conn.vendor == "sqlite":
        tables = conn.introspection.table_names()
        results = []
        with conn.cursor() as cursor:
            for table in sorted(tables):
                description = conn.introspection.get_table_description(cursor, table)
                cols = []
                for col in description:
                    col_type = (getattr(col, "type_code", "") or "").upper()
                    if "BLOB" in col_type:
                        cols.append({"column": col.name, "data_type": col_type.lower(), "max_length": None})
                if cols:
                    results.append({"table": table, "columns": cols})
        return results

    raise BlobMigrationError(f"暂不支持 {conn.vendor} 的 BLOB 表发现")


def _source_database_name(source: BlobMigrationSource) -> str | None:
    value = (getattr(source, "database_name", "") or "").strip()
    return value or None


def resolve_source_database_name(source: BlobMigrationSource) -> str:
    """Return persisted or inferred database name for remote scans."""
    direct = _source_database_name(source)
    if direct:
        return direct

    from images.models import BlobTableView

    view = (
        BlobTableView.objects.filter(
            db_alias=source.db_alias,
            source_table=source.source_table,
        )
        .exclude(database_name="")
        .order_by("-id")
        .first()
    )
    if view and (view.database_name or "").strip():
        return view.database_name.strip()

    from images.external_db_service import parse_external_alias

    ext_id = parse_external_alias(source.db_alias)
    if ext_id is not None:
        from images.models import ExternalDbConnection

        conn = ExternalDbConnection.objects.filter(pk=ext_id, enabled=1).first()
        if conn and (conn.db_name or "").strip():
            return conn.db_name.strip()

    return ""


def prepare_migration_source(source: BlobMigrationSource, *, persist: bool = True) -> BlobMigrationSource:
    """Ensure database_name and JOIN path mappings are ready before remote scans."""
    resolved = resolve_source_database_name(source)
    current = (getattr(source, "database_name", "") or "").strip()
    if resolved and resolved != current:
        if persist and source.pk:
            BlobMigrationSource.objects.filter(pk=source.pk).update(database_name=resolved)
        source.database_name = resolved
    source = _refresh_path_mappings_if_needed(source, persist=persist)
    return source


def _refresh_path_mappings_if_needed(source: BlobMigrationSource, *, persist: bool) -> BlobMigrationSource:
    """Backfill lookup_id_column on stored JOIN view mappings from the view SQL."""
    mappings = _path_mappings(source)
    if not mappings or normalize_object_type(source.source_object_type) != OBJECT_TYPE_VIEW:
        return source
    if all((m.get("lookup_id_column") or "").strip() for m in mappings):
        return source
    try:
        blob_cols = _source_blob_columns(source)
        with _source_db_session(source) as alias:
            conn = _remote_connection(alias)
            if conn.vendor != "mysql":
                return source
            from images.blob_view_path_service import infer_view_path_mappings

            db_name = _source_database_name(source) or str(conn.settings_dict.get("NAME") or "")
            inferred = {
                m["view_column"]: m
                for m in infer_view_path_mappings(
                    conn,
                    database=db_name,
                    object_name=source.source_table,
                    blob_columns=blob_cols,
                )
            }
    except Exception:
        logger.warning(
            "refresh path mappings failed source_id=%s table=%s",
            source.id,
            source.source_table,
            exc_info=True,
        )
        return source

    updated = False
    merged: list[dict[str, str]] = []
    for mapping in mappings:
        item = dict(mapping)
        if not (item.get("lookup_id_column") or "").strip():
            fresh = inferred.get(item.get("view_column") or "")
            if fresh and fresh.get("lookup_id_column"):
                item["lookup_id_column"] = fresh["lookup_id_column"]
                updated = True
        merged.append(item)
    if not updated:
        return source
    serialized = serialize_blob_column_path_mappings(merged)
    source.blob_column_path_mappings = serialized
    if persist and source.pk:
        BlobMigrationSource.objects.filter(pk=source.pk).update(
            blob_column_path_mappings=serialized,
        )
    return source


def _source_db_session(source: BlobMigrationSource):
    """Open the correct remote DB for a migration source (alias + optional database)."""
    return db_alias_session(source.db_alias, database=_source_database_name(source))


def _remote_connection(conn_alias: str):
    """Connection for remote scans; caller must hold _source_db_session."""
    return connections[conn_alias]


def _live_image_subquery():
    return ImageInfo.objects.filter(is_delete=0).values("id")


def _map_exists_for_migration(
    *,
    lookup_table: str,
    source_id: str,
    map_column: str,
    blob_columns: list[str],
) -> bool:
    """True only when a live image_source_map points at a non-deleted image_info."""
    live_images = ImageInfo.objects.filter(is_delete=0).values("id")
    qs = ImageSourceMap.objects.filter(
        source_table=lookup_table,
        source_id=source_id,
        image_info_id__in=live_images,
    )
    if qs.filter(source_column=map_column).exists():
        return True
    if len(blob_columns) == 1 and map_column == blob_columns[0]:
        return qs.filter(source_column="").exists()
    return False


def _probe_remote_blob_rows(source: BlobMigrationSource) -> dict[str, Any]:
    """Cheap sanity check before walking the cursor."""
    blob_cols = _source_blob_columns(source)
    with _source_db_session(source) as alias:
        conn = _remote_connection(alias)
        table = _quote_ident(source.source_table)
        extra = validate_where_clause(source.where_clause)
        where_sql = f" WHERE ({extra})" if extra else ""
        blob_checks = [_blob_nonempty_sql(conn, _quote_ident(col)) for col in blob_cols]
        blob_where = f"({' OR '.join(blob_checks)})"
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {table}{where_sql}")
            table_rows = int((cursor.fetchone() or [0])[0] or 0)
            cursor.execute(f"SELECT COUNT(*) FROM {table}{where_sql}{' AND ' if where_sql else ' WHERE '}{blob_where}")
            blob_rows = int((cursor.fetchone() or [0])[0] or 0)
            current_db = ""
            try:
                cursor.execute("SELECT DATABASE()")
                current_db = str((cursor.fetchone() or [""])[0] or "")
            except Exception:
                pass
    return {
        "database": current_db or _source_database_name(source) or source.db_alias,
        "table_rows": table_rows,
        "blob_rows": blob_rows,
        "blob_columns": blob_cols,
    }


def _quote_ident(name: str) -> str:
    return f"`{validate_identifier(name)}`"


def _load_source(source_id: int) -> BlobMigrationSource:
    try:
        return BlobMigrationSource.objects.get(pk=source_id)
    except BlobMigrationSource.DoesNotExist as exc:
        raise BlobMigrationError(f"迁移配置不存在: id={source_id}") from exc


def _source_blob_columns(source: BlobMigrationSource) -> list[str]:
    cols = parse_blob_columns(source.blob_columns, source.blob_column)
    if not cols:
        raise BlobMigrationError("至少需要一个 BLOB 列")
    for col in cols:
        validate_identifier(col, label="BLOB 列")
    return cols


def _storage_table(source: BlobMigrationSource) -> str:
    try:
        return map_storage_table(
            source_table=source.source_table,
            source_object_type=source.source_object_type,
            path_lookup_table=source.path_lookup_table,
        )
    except ValueError as exc:
        raise BlobMigrationError(str(exc)) from exc


def _path_mappings(source: BlobMigrationSource) -> list[dict[str, str]]:
    return parse_blob_column_path_mappings(getattr(source, "blob_column_path_mappings", ""))


def _mapping_for_column(source: BlobMigrationSource, blob_column: str) -> dict[str, str] | None:
    for item in _path_mappings(source):
        if item.get("view_column") == blob_column:
            return item
    return None


def _map_target_for_column(
    source: BlobMigrationSource,
    row: dict,
    blob_column: str,
) -> tuple[str, str, str]:
    """
    Resolve (storage_table, source_id, map_column) for image_source_map.

    JOIN views use per-column mappings so each BLOB lands on its base table.
    """
    mapping = _mapping_for_column(source, blob_column)
    if mapping:
        sid_col = mapping["source_id_column"]
        if sid_col not in row:
            raise BlobMigrationError(
                f"视图行缺少路径映射键列 {sid_col}（BLOB 列 {blob_column}）"
            )
        return (
            mapping["lookup_table"],
            str(row[sid_col]),
            mapping.get("source_column") or blob_column,
        )
    return _storage_table(source), str(row[source.source_pk_column]), blob_column


def _extra_select_columns(source: BlobMigrationSource) -> list[str]:
    """Columns needed beyond PK/BLOB for filename and per-column path mappings."""
    cols: list[str] = []
    seen = {source.source_pk_column, *_source_blob_columns(source)}
    for candidate in (
        source.name_column,
        source.suffix_column,
        *[m["source_id_column"] for m in _path_mappings(source)],
    ):
        name = (candidate or "").strip()
        if not name or name in seen:
            continue
        validate_identifier(name, label="列名")
        cols.append(name)
        seen.add(name)
    return cols


def _blob_nonempty_sql(conn, blob_quoted: str) -> str:
    """
    Cheap non-empty check for BLOB columns.

    Avoid LENGTH(blob): on MySQL/SQLite it forces reading the full binary value,
    which makes COUNT/cursor scans on large tables extremely slow.
    Empty image BLOBs are rare; IS NOT NULL is sufficient for migration scans.
    """
    return f"({blob_quoted} IS NOT NULL)"


def _cursor_candidate_checks(source: BlobMigrationSource, conn) -> list[str]:
    """
    Filters for finding migratable rows without reading BLOB bytes.

    JOIN views often expose NULL in view BLOB columns while bytes live on base
    tables; when path mappings exist, key columns are a reliable scan filter.
    """
    path_mappings = _path_mappings(source)
    if path_mappings:
        seen: set[str] = set()
        checks: list[str] = []
        for mapping in path_mappings:
            col = (mapping.get("source_id_column") or "").strip()
            if not col or col in seen:
                continue
            seen.add(col)
            checks.append(_blob_nonempty_sql(conn, _quote_ident(col)))
        if checks:
            return checks
    blob_cols = _source_blob_columns(source)
    return [_blob_nonempty_sql(conn, _quote_ident(col)) for col in blob_cols]


def _lookup_id_column(mapping: dict[str, str]) -> str:
    explicit = (mapping.get("lookup_id_column") or "").strip()
    if explicit:
        return explicit
    return (mapping.get("source_id_column") or "").strip()


def _fetch_blob_from_lookup_table(
    source: BlobMigrationSource,
    mapping: dict[str, str],
    row: dict,
) -> bytes | None:
    """Read BLOB bytes from the mapped base table when the view column is NULL."""
    lookup_table = (mapping.get("lookup_table") or "").strip()
    blob_col = (mapping.get("source_column") or mapping.get("view_column") or "").strip()
    sid_col = (mapping.get("source_id_column") or "").strip()
    lookup_id_col = _lookup_id_column(mapping)
    if not lookup_table or not blob_col or not sid_col or not lookup_id_col:
        return None
    if sid_col not in row:
        return None
    lookup_id_val = row[sid_col]
    if lookup_id_val is None:
        return None

    table = _quote_ident(lookup_table)
    blob = _quote_ident(blob_col)
    id_col = _quote_ident(lookup_id_col)
    sql = f"SELECT {blob} FROM {table} WHERE {id_col} = %s LIMIT 1"
    with _source_db_session(source) as alias:
        conn = _remote_connection(alias)
        with conn.cursor() as cursor:
            cursor.execute(sql, [lookup_id_val])
            raw = cursor.fetchone()
    if not raw:
        return None
    return _coerce_blob(raw[0])


def _blob_bytes_for_column(source: BlobMigrationSource, row: dict, blob_column: str) -> bytes | None:
    content = _coerce_blob(row.get(blob_column))
    if content:
        return content
    mapping = _mapping_for_column(source, blob_column)
    if not mapping:
        return None
    return _fetch_blob_from_lookup_table(source, mapping, row)


def _validate_source_config(source: BlobMigrationSource) -> None:
    validate_identifier(source.source_table, label="源表名")
    validate_identifier(source.source_pk_column, label="主键列")
    _source_blob_columns(source)
    if source.name_column:
        validate_identifier(source.name_column, label="文件名列")
    if source.suffix_column:
        validate_identifier(source.suffix_column, label="后缀列")
    if source.path_lookup_table:
        validate_identifier(source.path_lookup_table, label="路径映射表")
    validate_where_clause(source.where_clause)
    validate_db_alias(source.db_alias)
    _storage_table(source)
    if not ImageCategory.objects.filter(id=source.category_id).exists():
        raise BlobMigrationError(f"分类不存在: id={source.category_id}")


def _infer_filename(
    *,
    source_id: str,
    content: bytes,
    name_value: str | None,
    suffix_value: str | None,
    source_table: str,
) -> str:
    raw_name = (name_value or "").strip()
    raw_suffix = (suffix_value or "").strip().lstrip(".")

    if raw_name:
        candidate = Path(raw_name).name
        if extension_from_filename(candidate):
            return candidate
        detected = detect_image_type(content[:32])
        if detected:
            stem = Path(candidate).stem or candidate
            return f"{stem}.{detected}"
        if raw_suffix:
            return f"{candidate}.{normalize_suffix(raw_suffix)}"

    detected = detect_image_type(content[:32])
    suffix = normalize_suffix(raw_suffix) if raw_suffix else (detected or "bin")
    if not detected and suffix in {"jpg", "jpeg", "png", "gif", "webp", "bmp"}:
        detected = suffix
    if not detected:
        raise BlobMigrationError("无法识别图片格式（魔数校验失败）")
    return f"{source_table}_{source_id}.{detected}"


def _coerce_blob(value) -> bytes:
    if value is None:
        return b""
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    raise BlobMigrationError("BLOB 列返回值类型无效")


@dataclass
class _MigrationBatchContext:
    """Bulk-loaded image_source_map keys for one batch — avoids per-row exists queries."""

    storage_table: str
    blob_columns: list[str]
    migrated_keys: set[tuple[str, str, str]]  # (lookup_table, source_id, map_column)
    path_mappings: list[dict[str, str]]

    @classmethod
    def load(cls, source: BlobMigrationSource, light_rows: list[dict]) -> _MigrationBatchContext:
        storage_table = _storage_table(source)
        blob_columns = _source_blob_columns(source)
        path_mappings = _path_mappings(source)
        migrated_keys: set[tuple[str, str, str]] = set()
        if not light_rows:
            return cls(
                storage_table=storage_table,
                blob_columns=blob_columns,
                migrated_keys=migrated_keys,
                path_mappings=path_mappings,
            )

        # Group lookup keys by (lookup_table, map_column) for efficient queries.
        targets_by_table: dict[str, set[str]] = {}
        map_columns_by_table: dict[str, set[str]] = {}
        for light in light_rows:
            for col in blob_columns:
                try:
                    lookup_table, source_id, map_column = _map_target_for_column(source, light, col)
                except BlobMigrationError:
                    continue
                targets_by_table.setdefault(lookup_table, set()).add(source_id)
                map_columns_by_table.setdefault(lookup_table, set()).add(map_column)
                if len(blob_columns) == 1:
                    map_columns_by_table[lookup_table].add("")

        for lookup_table, source_ids in targets_by_table.items():
            cols = list(map_columns_by_table.get(lookup_table) or [])
            rows = ImageSourceMap.objects.filter(
                source_table=lookup_table,
                source_id__in=list(source_ids),
                image_info_id__in=_live_image_subquery(),
            )
            if cols:
                rows = rows.filter(source_column__in=cols)
            for source_id, source_column in rows.values_list("source_id", "source_column"):
                col = (source_column or "").strip()
                if col:
                    migrated_keys.add((lookup_table, str(source_id), col))
                elif len(blob_columns) == 1:
                    migrated_keys.add((lookup_table, str(source_id), blob_columns[0]))

        return cls(
            storage_table=storage_table,
            blob_columns=blob_columns,
            migrated_keys=migrated_keys,
            path_mappings=path_mappings,
        )

    def is_migrated(self, lookup_table: str, source_id: str, map_column: str) -> bool:
        return (lookup_table, source_id, map_column) in self.migrated_keys

    def is_row_column_migrated(self, source: BlobMigrationSource, row: dict, blob_column: str) -> bool:
        try:
            lookup_table, source_id, map_column = _map_target_for_column(source, row, blob_column)
        except BlobMigrationError:
            return False
        return self.is_migrated(lookup_table, source_id, map_column)


@dataclass
class _PreparedMigrationBatch:
    rows_fetched: int
    last_pk: str
    blob_rows: list[dict]
    pre_skipped: list[MigrationItemResult]
    map_ctx: _MigrationBatchContext | None = None


def _cursor_where_parts(
    source: BlobMigrationSource,
    conn,
    *,
    after_pk: str = "",
) -> tuple[list[str], list, str]:
    """Shared WHERE clause for cursor scans over legacy source rows."""
    pk_col_name = source.source_pk_column
    pk = _quote_ident(pk_col_name)

    blob_checks = _cursor_candidate_checks(source, conn)
    where_parts = ["(" + " OR ".join(blob_checks) + ")"]
    params: list = []
    extra = validate_where_clause(source.where_clause)
    if extra:
        where_parts.append(f"({extra})")
    if after_pk:
        where_parts.append(f"{pk} > %s")
        params.append(after_pk)
    return where_parts, params, pk


def _fetch_source_pks_cursor(
    source: BlobMigrationSource,
    *,
    conn_alias: str,
    after_pk: str = "",
    limit: int = 1,
) -> list[dict]:
    """Light scan: PK (+ optional name/suffix) without reading BLOB columns."""
    conn = _remote_connection(conn_alias)
    table = _quote_ident(source.source_table)
    pk_col_name = source.source_pk_column
    where_parts, params, pk = _cursor_where_parts(source, conn, after_pk=after_pk)

    select_cols = [pk]
    for col in _extra_select_columns(source):
        select_cols.append(_quote_ident(col))

    sql = (
        f"SELECT {', '.join(select_cols)} FROM {table} "
        f"WHERE {' AND '.join(where_parts)} "
        f"ORDER BY {pk} "
        f"LIMIT %s"
    )
    params.append(limit)

    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, raw)) for raw in cursor.fetchall()]


def _fetch_source_rows_by_pks(
    source: BlobMigrationSource,
    pk_values: list[str],
    *,
    conn_alias: str,
) -> list[dict]:
    """Fetch full rows (including BLOB) for specific primary keys."""
    if not pk_values:
        return []

    conn = _remote_connection(conn_alias)
    table = _quote_ident(source.source_table)
    pk_col_name = source.source_pk_column
    pk = _quote_ident(pk_col_name)
    blob_cols = _source_blob_columns(source)

    select_cols = [pk] + [_quote_ident(col) for col in blob_cols]
    for col in _extra_select_columns(source):
        select_cols.append(_quote_ident(col))

    placeholders = ", ".join(["%s"] * len(pk_values))
    sql = f"SELECT {', '.join(select_cols)} FROM {table} WHERE {pk} IN ({placeholders}) ORDER BY {pk}"

    with conn.cursor() as cursor:
        cursor.execute(sql, pk_values)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, raw)) for raw in cursor.fetchall()]


def _prepare_migration_batch(
    source: BlobMigrationSource,
    *,
    after_pk: str,
    batch_size: int,
    skip_existing: bool,
) -> _PreparedMigrationBatch:
    """Two-phase batch prep: scan PKs first, bulk-check maps, fetch BLOB only when needed."""
    pk_col = source.source_pk_column

    with _source_db_session(source) as alias:
        light_rows = _fetch_source_pks_cursor(source, conn_alias=alias, after_pk=after_pk, limit=batch_size)

    if not light_rows:
        return _PreparedMigrationBatch(rows_fetched=0, last_pk=after_pk, blob_rows=[], pre_skipped=[])

    last_pk = str(light_rows[-1][pk_col])
    pk_values = [str(row[pk_col]) for row in light_rows]
    pre_skipped: list[MigrationItemResult] = []

    if not skip_existing:
        with _source_db_session(source) as alias:
            blob_rows = _fetch_source_rows_by_pks(source, pk_values, conn_alias=alias)
        return _PreparedMigrationBatch(
            rows_fetched=len(light_rows),
            last_pk=last_pk,
            blob_rows=blob_rows,
            pre_skipped=pre_skipped,
        )

    map_ctx = _MigrationBatchContext.load(source, light_rows)
    pks_needing_blob: list[str] = []
    for light in light_rows:
        source_id_str = str(light[pk_col])
        needs_blob = False
        for col in map_ctx.blob_columns:
            if map_ctx.is_row_column_migrated(source, light, col):
                pre_skipped.append(
                    MigrationItemResult(
                        source_id=source_id_str,
                        source_column=col,
                        success=True,
                        skipped=True,
                    )
                )
            else:
                needs_blob = True
        if needs_blob:
            pks_needing_blob.append(source_id_str)

    with _source_db_session(source) as alias:
        blob_rows = _fetch_source_rows_by_pks(source, pks_needing_blob, conn_alias=alias)
    return _PreparedMigrationBatch(
        rows_fetched=len(light_rows),
        last_pk=last_pk,
        blob_rows=blob_rows,
        pre_skipped=pre_skipped,
        map_ctx=map_ctx,
    )


def _fetch_source_rows_cursor(
    source: BlobMigrationSource,
    *,
    after_pk: str = "",
    limit: int = 1,
) -> list[dict]:
    """Full-row cursor fetch (legacy path for single-row retry lookups)."""
    prepared = _prepare_migration_batch(
        source,
        after_pk=after_pk,
        batch_size=limit,
        skip_existing=False,
    )
    return prepared.blob_rows


def _fetch_source_row_by_pk(source: BlobMigrationSource, pk_value: str) -> dict | None:
    table = _quote_ident(source.source_table)
    pk = _quote_ident(source.source_pk_column)
    blob_cols = _source_blob_columns(source)

    select_cols = [pk] + [_quote_ident(col) for col in blob_cols]
    for col in _extra_select_columns(source):
        select_cols.append(_quote_ident(col))

    sql = f"SELECT {', '.join(select_cols)} FROM {table} WHERE {pk} = %s LIMIT 1"
    with _source_db_session(source) as alias:
        conn = _remote_connection(alias)
        with conn.cursor() as cursor:
            cursor.execute(sql, [pk_value])
            columns = [col[0] for col in cursor.description]
            raw = cursor.fetchone()
    if not raw:
        return None
    return dict(zip(columns, raw))


def _is_already_migrated(source: BlobMigrationSource, row: dict, blob_column: str) -> bool:
    lookup_table, source_id_str, map_column = _map_target_for_column(source, row, blob_column)
    return _map_exists_for_migration(
        lookup_table=lookup_table,
        source_id=source_id_str,
        map_column=map_column,
        blob_columns=_source_blob_columns(source),
    )


def _upsert_source_map(
    *,
    lookup_table: str,
    map_source_id: str,
    map_column: str,
    image_info_id: int,
) -> None:
    """Create or refresh mapping — stale rows without live image_info are overwritten."""
    ImageSourceMap.objects.update_or_create(
        source_table=lookup_table,
        source_id=map_source_id,
        source_column=map_column,
        defaults={
            "image_info_id": image_info_id,
            "migrated_at": timezone.now(),
        },
    )


def _migrate_single_column(
    source: BlobMigrationSource,
    row: dict,
    *,
    blob_column: str,
    actor: str,
    dry_run: bool,
    skip_existing: bool,
) -> MigrationItemResult:
    pk_col = source.source_pk_column
    row_pk = str(row[pk_col])
    lookup_table, map_source_id, map_column = _map_target_for_column(source, row, blob_column)

    if skip_existing and _is_already_migrated(source, row, blob_column):
        return MigrationItemResult(
            source_id=row_pk,
            source_column=blob_column,
            success=True,
            skipped=True,
        )

    try:
        content = _blob_bytes_for_column(source, row, blob_column)
        if not content:
            return MigrationItemResult(
                source_id=row_pk,
                source_column=blob_column,
                success=True,
                skipped=True,
            )

        name_value = row.get(source.name_column) if source.name_column else None
        suffix_value = row.get(source.suffix_column) if source.suffix_column else None
        filename = _infer_filename(
            source_id=map_source_id,
            content=content,
            name_value=str(name_value) if name_value is not None else None,
            suffix_value=str(suffix_value) if suffix_value is not None else None,
            source_table=lookup_table,
        )
        if len(_source_blob_columns(source)) > 1:
            stem = Path(filename).stem
            ext = Path(filename).suffix
            filename = f"{stem}_{blob_column}{ext}" if ext else f"{filename}_{blob_column}"

        if dry_run:
            return MigrationItemResult(
                source_id=row_pk,
                source_column=blob_column,
                success=True,
                filename=filename,
            )

        image = save_image_bytes_for_migration(
            filename=filename,
            content=content,
            upload_user=actor,
            category_id=source.category_id,
            tags=source.tags,
        )
        _upsert_source_map(
            lookup_table=lookup_table,
            map_source_id=map_source_id,
            map_column=map_column,
            image_info_id=image.id,
        )
        return MigrationItemResult(
            source_id=row_pk,
            source_column=blob_column,
            success=True,
            image_info_id=image.id,
            filename=filename,
        )
    except DuplicateImageError as exc:
        if dry_run:
            return MigrationItemResult(
                source_id=row_pk,
                source_column=blob_column,
                success=True,
                skipped=True,
                filename=getattr(exc, "filename", ""),
                error="已存在相同图片",
            )
        existing = exc.existing
        _upsert_source_map(
            lookup_table=lookup_table,
            map_source_id=map_source_id,
            map_column=map_column,
            image_info_id=existing.id,
        )
        return MigrationItemResult(
            source_id=row_pk,
            source_column=blob_column,
            success=True,
            skipped=True,
            image_info_id=existing.id,
            filename=getattr(exc, "filename", ""),
            error="已存在相同图片，已建立映射",
        )
    except Exception as exc:
        logger.exception(
            "blob migration failed source=%s id=%s column=%s",
            source.source_table,
            row_pk,
            blob_column,
        )
        return MigrationItemResult(
            source_id=row_pk,
            source_column=blob_column,
            success=False,
            error=str(exc),
        )


def _build_work_units(
    source: BlobMigrationSource,
    blob_rows: list[dict],
    *,
    skip_existing: bool,
    map_ctx: _MigrationBatchContext | None,
) -> list[tuple[dict, str]]:
    blob_cols = _source_blob_columns(source)
    work: list[tuple[dict, str]] = []
    for row in blob_rows:
        for col in blob_cols:
            if skip_existing and map_ctx and map_ctx.is_row_column_migrated(source, row, col):
                continue
            work.append((row, col))
    return work


def _migrate_work_unit(
    source: BlobMigrationSource,
    row: dict,
    blob_column: str,
    *,
    actor: str,
    dry_run: bool,
) -> MigrationItemResult:
    return _migrate_single_column(
        source,
        row,
        blob_column=blob_column,
        actor=actor,
        dry_run=dry_run,
        skip_existing=False,
    )


def _record_batch_item(
    batch: MigrationBatchResult,
    item: MigrationItemResult,
    *,
    job: BlobMigrationJob | None,
    items: list[MigrationItemResult],
    include_items: bool,
    items_cap: int,
) -> None:
    _apply_item_to_batch(batch, item)
    if include_items and len(items) < items_cap:
        items.append(item)
    if job and not item.success and not item.skipped:
        _record_job_error(
            job.id,
            source_pk=item.source_id,
            source_column=item.source_column,
            filename=item.filename,
            error=item.error or "unknown",
        )


def _migrate_row(
    source: BlobMigrationSource,
    row: dict,
    *,
    actor: str,
    dry_run: bool,
    skip_existing: bool,
    blob_column: str | None = None,
) -> list[MigrationItemResult]:
    columns = [blob_column] if blob_column else _source_blob_columns(source)
    return [
        _migrate_single_column(
            source,
            row,
            blob_column=col,
            actor=actor,
            dry_run=dry_run,
            skip_existing=skip_existing,
        )
        for col in columns
    ]


def _apply_item_to_batch(batch: MigrationBatchResult, item: MigrationItemResult) -> None:
    batch.processed += 1
    if item.skipped:
        batch.skipped += 1
    elif item.success:
        batch.succeeded += 1
    else:
        batch.failed += 1


def _run_migration_batch_cursor(
    source: BlobMigrationSource,
    *,
    batch_size: int,
    after_pk: str,
    dry_run: bool,
    skip_existing: bool,
    upload_user: str,
    job: BlobMigrationJob | None = None,
    include_items: bool = False,
    items_cap: int = 100,
) -> tuple[MigrationBatchResult, list[MigrationItemResult]]:
    actor = upload_user or source.upload_user or "migration"
    batch = MigrationBatchResult()
    items: list[MigrationItemResult] = []

    prepared = _prepare_migration_batch(
        source,
        after_pk=after_pk,
        batch_size=batch_size,
        skip_existing=skip_existing,
    )
    batch.rows_fetched = prepared.rows_fetched
    if not prepared.rows_fetched:
        return batch, items

    batch.last_pk = prepared.last_pk
    for item in prepared.pre_skipped:
        _record_batch_item(batch, item, job=job, items=items, include_items=include_items, items_cap=items_cap)

    # Flush pre-skipped counts early so the UI moves before BLOB I/O starts.
    if job and batch.processed:
        _update_job_progress(job, batch, last_pk=prepared.last_pk)
        batch = MigrationBatchResult(rows_fetched=prepared.rows_fetched, last_pk=prepared.last_pk)

    work_units = _build_work_units(
        source,
        prepared.blob_rows,
        skip_existing=skip_existing,
        map_ctx=prepared.map_ctx,
    )
    if not work_units:
        return batch, items

    workers = 1 if dry_run else _upload_workers()
    flush_every = 5

    if workers <= 1:
        for row, col in work_units:
            if job and _job_cancelled(job.id):
                break
            item = _migrate_work_unit(source, row, col, actor=actor, dry_run=dry_run)
            _record_batch_item(batch, item, job=job, items=items, include_items=include_items, items_cap=items_cap)
            if job and batch.processed >= flush_every:
                _update_job_progress(job, batch, last_pk=prepared.last_pk)
                batch = MigrationBatchResult(rows_fetched=prepared.rows_fetched, last_pk=prepared.last_pk)
    else:
        lock = Lock()

        def _task(row: dict, col: str) -> MigrationItemResult:
            close_old_connections()
            try:
                return _migrate_work_unit(source, row, col, actor=actor, dry_run=dry_run)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_task, row, col): (row, col) for row, col in work_units}
            for future in as_completed(futures):
                if job and _job_cancelled(job.id):
                    break
                item = future.result()
                with lock:
                    _record_batch_item(
                        batch, item, job=job, items=items, include_items=include_items, items_cap=items_cap
                    )
                    if job and batch.processed >= flush_every:
                        _update_job_progress(job, batch, last_pk=prepared.last_pk)
                        batch = MigrationBatchResult(rows_fetched=prepared.rows_fetched, last_pk=prepared.last_pk)

    return batch, items


def _job_handled_count(job: BlobMigrationJob) -> int:
    return int(job.succeeded or 0) + int(job.failed or 0) + int(job.skipped or 0)


def _sync_job_estimate_from_handled(job: BlobMigrationJob) -> None:
    """Grow UI-only total_estimate when processed rows exceed the pre-count."""
    handled = _job_handled_count(job)
    if handled > int(job.total_estimate or 0):
        BlobMigrationJob.objects.filter(pk=job.pk).update(
            total_estimate=handled,
            updated_at=timezone.now(),
        )


def _record_empty_scan_diagnostic(job: BlobMigrationJob, source: BlobMigrationSource) -> None:
    try:
        with _source_db_session(source) as alias:
            conn = _remote_connection(alias)
            table = _quote_ident(source.source_table)
            extra = validate_where_clause(source.where_clause)
            where_sql = f" WHERE ({extra})" if extra else ""
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {table}{where_sql}")
                table_rows = int((cursor.fetchone() or [0])[0] or 0)
                current_db = ""
                try:
                    cursor.execute("SELECT DATABASE()")
                    current_db = str((cursor.fetchone() or [""])[0] or "")
                except Exception:
                    pass
        BlobMigrationJob.objects.filter(pk=job.pk).update(
            message=(
                f"源表扫描无 BLOB 候选行（库={current_db or _source_database_name(source) or source.db_alias} "
                f"表={source.source_table} 行数={table_rows} "
                f"WHERE={source.where_clause or '无'}）"
            )[:500],
            updated_at=timezone.now(),
        )
    except Exception:
        logger.warning(
            "empty-scan diagnostic failed job_id=%s source_id=%s",
            job.id,
            source.id,
            exc_info=True,
        )


def execute_migration_job_batches(job: BlobMigrationJob) -> None:
    """Walk the source cursor until exhausted.

    total_estimate is UI-only and never gates whether batches run.
    """
    source = prepare_migration_source(_load_source(job.source_id))
    _validate_source_config(source)
    batch_size = _max_batch_size(job.batch_size)
    blob_cols = _source_blob_columns(source)
    cols_label = ",".join(blob_cols)
    db_label = _source_database_name(source) or source.db_alias
    BlobMigrationJob.objects.filter(pk=job.pk).update(
        message=(
            f"迁移进行中（库={db_label} 表={source.source_table} BLOB列={cols_label}）"
        )[:500],
        updated_at=timezone.now(),
    )

    batches_run = 0

    while True:
        job.refresh_from_db()
        if job.cancel_requested:
            return

        batch, _ = _run_migration_batch_cursor(
            source,
            batch_size=batch_size,
            after_pk=job.last_pk_cursor or "",
            dry_run=bool(job.dry_run),
            skip_existing=bool(job.skip_existing),
            upload_user=job.created_by,
            job=job,
        )
        if batch.rows_fetched == 0:
            if batches_run == 0:
                _record_empty_scan_diagnostic(job, source)
            break

        batches_run += 1
        _update_job_progress(job, batch, last_pk=batch.last_pk or job.last_pk_cursor)
        job.refresh_from_db()
        _sync_job_estimate_from_handled(job)

        if not job.run_all:
            break

    if not job.dry_run:
        BlobMigrationSource.objects.filter(pk=source.pk).update(last_run_at=timezone.now())
    invalidate_migration_stats_cache(source.id)


def retry_failed_rows_for_job(job: BlobMigrationJob) -> None:
    if not job.parent_job_id:
        raise BlobMigrationError("重试任务缺少 parent_job_id")

    source = _load_source(job.source_id)
    _validate_source_config(source)
    actor = job.created_by or source.upload_user or "migration"
    errors = list(
        BlobMigrationJobError.objects.filter(job_id=job.parent_job_id, retried=0).order_by("id")
    )
    batch = MigrationBatchResult(rows_fetched=len(errors))
    increment = MigrationBatchResult()

    with _source_db_session(source):
        for err in errors:
            job.refresh_from_db()
            if job.cancel_requested:
                break

            row = _fetch_source_row_by_pk(source, err.source_pk)
            if row is None:
                item = MigrationItemResult(
                    source_id=err.source_pk,
                    source_column=err.source_column or "",
                    success=False,
                    error="源表记录不存在",
                )
            else:
                target_col = (err.source_column or "").strip() or None
                results = _migrate_row(
                    source,
                    row,
                    actor=actor,
                    dry_run=bool(job.dry_run),
                    skip_existing=False,
                    blob_column=target_col,
                )
                item = results[0] if len(results) == 1 else results[-1]

            _apply_item_to_batch(increment, item)
            _apply_item_to_batch(batch, item)
            if item.success and not item.skipped:
                BlobMigrationJobError.objects.filter(pk=err.pk).update(retried=1)
            elif not item.success:
                _record_job_error(
                    job.id,
                    source_pk=item.source_id,
                    source_column=item.source_column or err.source_column,
                    filename=item.filename or err.filename,
                    error=item.error or "retry failed",
                )

            if increment.processed >= 10:
                _update_job_progress(job, increment, last_pk=None)
                increment = MigrationBatchResult()

    if increment.processed:
        _update_job_progress(job, increment, last_pk=None)
    if not job.dry_run:
        BlobMigrationSource.objects.filter(pk=source.pk).update(last_run_at=timezone.now())
    invalidate_migration_stats_cache(source.id)


def count_migration_candidates(source_id: int, *, use_cache: bool = True) -> dict:
    source = prepare_migration_source(_load_source(source_id))
    _validate_source_config(source)
    blob_cols = _source_blob_columns(source)
    storage_table = _storage_table(source)
    path_mappings = _path_mappings(source)
    mapping_by_col = {m["view_column"]: m for m in path_mappings}

    cache_key = (
        source.id,
        _source_database_name(source) or "",
        source.source_table,
        source.where_clause or "",
        tuple(blob_cols),
        source.path_lookup_table or "",
        getattr(source, "blob_column_path_mappings", "") or "",
    )
    now = time.monotonic()
    if use_cache:
        with _STATS_CACHE_LOCK:
            cached = _STATS_CACHE.get(cache_key)
            if cached and now - cached[0] < _STATS_CACHE_TTL_SECONDS:
                return dict(cached[1])

    with _source_db_session(source) as alias:
        conn = _remote_connection(alias)
        table = _quote_ident(source.source_table)
        extra = validate_where_clause(source.where_clause)
        where_parts: list[str] = []
        if extra:
            where_parts.append(f"({extra})")
        if path_mappings:
            checks = _cursor_candidate_checks(source, conn)
            if checks:
                where_parts.append("(" + " OR ".join(checks) + ")")
            sql = f"SELECT COUNT(*) FROM {table}"
            if where_parts:
                sql += f" WHERE {' AND '.join(where_parts)}"
            with conn.cursor() as cursor:
                cursor.execute(sql)
                rows_with_keys = int((cursor.fetchone() or [0])[0] or 0)
            total_with_blob = rows_with_keys * max(1, len(blob_cols))
        else:
            where_sql = f" WHERE ({extra})" if extra else ""
            select_parts = [
                f"SUM(CASE WHEN {_blob_nonempty_sql(conn, _quote_ident(col))} THEN 1 ELSE 0 END)"
                for col in blob_cols
            ]
            sql = f"SELECT {', '.join(select_parts)} FROM {table}{where_sql}"
            with conn.cursor() as cursor:
                cursor.execute(sql)
                row = cursor.fetchone() or ()
            total_with_blob = sum(int(v or 0) for v in row)

    live_maps = ImageSourceMap.objects.filter(image_info_id__in=_live_image_subquery())
    migrated = 0
    if path_mappings:
        seen_keys: set[tuple[str, str]] = set()
        for col in blob_cols:
            mapping = mapping_by_col.get(col)
            if not mapping:
                continue
            key = (mapping["lookup_table"], mapping.get("source_column") or col)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            lookup_table, map_column = key
            migrated += live_maps.filter(
                source_table=lookup_table,
                source_column=map_column,
            ).count()
            if len(blob_cols) == 1:
                migrated += live_maps.filter(
                    source_table=lookup_table,
                    source_column="",
                ).count()
    else:
        migrated = live_maps.filter(
            source_table=storage_table,
            source_column__in=blob_cols,
        ).count()
        if len(blob_cols) == 1:
            migrated += live_maps.filter(
                source_table=storage_table,
                source_column="",
            ).count()

    result = {
        "source_id": source.id,
        "source_table": source.source_table,
        "storage_table": storage_table,
        "db_alias": source.db_alias,
        "blob_columns": blob_cols,
        "source_object_type": source.source_object_type,
        "path_lookup_table": source.path_lookup_table,
        "blob_column_path_mappings": path_mappings,
        "total_with_blob": total_with_blob,
        "migrated": migrated,
        "pending": max(total_with_blob - migrated, 0),
    }
    if use_cache:
        with _STATS_CACHE_LOCK:
            _STATS_CACHE[cache_key] = (now, dict(result))
            if len(_STATS_CACHE) > 64:
                oldest = sorted(_STATS_CACHE.items(), key=lambda item: item[1][0])[:16]
                for key, _ in oldest:
                    _STATS_CACHE.pop(key, None)
    return result


def invalidate_migration_stats_cache(source_id: int | None = None) -> None:
    with _STATS_CACHE_LOCK:
        if source_id is None:
            _STATS_CACHE.clear()
            return
        for key in list(_STATS_CACHE):
            if key and key[0] == source_id:
                _STATS_CACHE.pop(key, None)


def run_blob_migration(
    source_id: int,
    *,
    batch_size: int = 50,
    dry_run: bool = False,
    skip_existing: bool = True,
    upload_user: str | None = None,
) -> MigrationRunResult:
    source = prepare_migration_source(_load_source(source_id))
    _validate_source_config(source)

    if batch_size <= 0:
        raise BlobMigrationError("batch_size 必须大于 0")
    batch_size = _max_batch_size(batch_size)

    result = MigrationRunResult(
        source_id=source.id,
        source_table=source.source_table,
        dry_run=dry_run,
    )

    batch, items = _run_migration_batch_cursor(
        source,
        batch_size=batch_size,
        after_pk="",
        dry_run=dry_run,
        skip_existing=skip_existing,
        upload_user=upload_user or source.upload_user or "migration",
        job=None,
        include_items=True,
        items_cap=500,
    )
    result.total_candidates = batch.rows_fetched
    result.processed = batch.processed
    result.succeeded = batch.succeeded
    result.failed = batch.failed
    result.skipped = batch.skipped
    result.items = items

    if not dry_run:
        BlobMigrationSource.objects.filter(pk=source.pk).update(last_run_at=timezone.now())
    invalidate_migration_stats_cache(source.id)

    return result


def create_migration_source(**fields) -> BlobMigrationSource:
    from images.blob_view_path_service import BlobViewPathError, resolve_source_metadata

    blob_columns_raw = fields.get("blob_columns")
    if isinstance(blob_columns_raw, list):
        blob_columns_list = [str(col).strip() for col in blob_columns_raw if str(col).strip()]
    else:
        blob_columns_list = parse_blob_columns(
            blob_columns_raw if isinstance(blob_columns_raw, str) else None,
            fields.get("blob_column"),
        )

    db_alias = fields.get("db_alias") or "default"
    initial_db = (fields.get("database_name") or "").strip()
    with db_alias_session(db_alias, database=initial_db or None) as alias:
        conn = connections[alias]
        db_name = initial_db or str(conn.settings_dict.get("NAME") or "")
        try:
            meta = resolve_source_metadata(
                conn,
                database=db_name,
                object_name=fields["source_table"],
                object_type=fields.get("source_object_type"),
                path_lookup_table=fields.get("path_lookup_table"),
                blob_columns=blob_columns_list or None,
                blob_column=fields.get("blob_column"),
            )
        except BlobViewPathError as exc:
            raise BlobMigrationError(str(exc)) from exc

    source = BlobMigrationSource(
        name=fields.get("name", ""),
        source_table=fields["source_table"],
        source_pk_column=fields.get("source_pk_column") or "id",
        blob_column=meta["blob_column"],
        blob_columns=serialize_blob_columns(meta["blob_columns"]),
        source_object_type=meta["source_object_type"],
        path_lookup_table=meta["path_lookup_table"],
        blob_column_path_mappings=serialize_blob_column_path_mappings(
            fields.get("blob_column_path_mappings")
            or meta.get("blob_column_path_mappings")
            or []
        ),
        name_column=fields.get("name_column") or "",
        suffix_column=fields.get("suffix_column") or "",
        category_id=fields["category_id"],
        upload_user=fields.get("upload_user") or "migration",
        tags=(fields.get("tags") or "")[:500],
        where_clause=fields.get("where_clause") or "",
        db_alias=db_alias,
        database_name=db_name,
        enabled=1,
        create_time=timezone.now(),
    )
    _validate_source_config(source)
    source.save(force_insert=True)
    return source
