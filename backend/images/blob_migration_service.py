"""Migrate image BLOB columns from legacy tables into upload/ + image_info."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.db import connections
from django.utils import timezone

from images.external_db_service import (
    db_alias_session,
    list_database_aliases,
    validate_db_alias_reference,
)
from images.models import BlobMigrationSource, ImageCategory, ImageInfo, ImageSourceMap
from images.services import DuplicateImageError, save_image_bytes
from utils.file_security import detect_image_type, extension_from_filename, normalize_suffix

logger = logging.getLogger(__name__)

IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
FORBIDDEN_WHERE_RE = re.compile(
    r";|--|/\*|\*/|\b(DROP|DELETE|UPDATE|INSERT|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

BLOB_TYPES_MYSQL = frozenset({"blob", "tinyblob", "mediumblob", "longblob", "binary", "varbinary"})


class BlobMigrationError(Exception):
    pass


@dataclass
class MigrationItemResult:
    source_id: str
    success: bool
    image_info_id: int | None = None
    filename: str = ""
    error: str = ""
    skipped: bool = False


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
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND DATA_TYPE IN ('blob', 'tinyblob', 'mediumblob', 'longblob', 'binary', 'varbinary')
                ORDER BY TABLE_NAME, ORDINAL_POSITION
                """
            )
            rows = cursor.fetchall()
        grouped: dict[str, list[dict]] = {}
        for table_name, column_name, data_type, max_len in rows:
            grouped.setdefault(table_name, []).append(
                {
                    "column": column_name,
                    "data_type": data_type,
                    "max_length": max_len,
                }
            )
        return [{"table": table, "columns": cols} for table, cols in sorted(grouped.items())]

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


def _quote_ident(name: str) -> str:
    return f"`{validate_identifier(name)}`"


def _load_source(source_id: int) -> BlobMigrationSource:
    try:
        return BlobMigrationSource.objects.get(pk=source_id)
    except BlobMigrationSource.DoesNotExist as exc:
        raise BlobMigrationError(f"迁移配置不存在: id={source_id}") from exc


def _validate_source_config(source: BlobMigrationSource) -> None:
    validate_identifier(source.source_table, label="源表名")
    validate_identifier(source.source_pk_column, label="主键列")
    validate_identifier(source.blob_column, label="BLOB 列")
    if source.name_column:
        validate_identifier(source.name_column, label="文件名列")
    if source.suffix_column:
        validate_identifier(source.suffix_column, label="后缀列")
    validate_where_clause(source.where_clause)
    validate_db_alias(source.db_alias)
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


def _fetch_source_rows(source: BlobMigrationSource, *, limit: int, offset: int = 0) -> list[dict]:
    conn = connections[source.db_alias]
    table = _quote_ident(source.source_table)
    pk = _quote_ident(source.source_pk_column)
    blob = _quote_ident(source.blob_column)

    select_cols = [pk, blob]
    if source.name_column:
        select_cols.append(_quote_ident(source.name_column))
    if source.suffix_column:
        select_cols.append(_quote_ident(source.suffix_column))

    where_parts = [f"{blob} IS NOT NULL"]
    params: list = []
    extra = validate_where_clause(source.where_clause)
    if extra:
        where_parts.append(f"({extra})")

    if conn.vendor == "mysql":
        where_parts.append(f"LENGTH({blob}) > 0")
    else:
        where_parts.append(f"length({blob}) > 0")

    sql = (
        f"SELECT {', '.join(select_cols)} FROM {table} "
        f"WHERE {' AND '.join(where_parts)} "
        f"ORDER BY {pk} "
        f"LIMIT %s OFFSET %s"
    )
    params.extend([limit, offset])

    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        raw_rows = cursor.fetchall()

    rows: list[dict] = []
    for raw in raw_rows:
        row = dict(zip(columns, raw))
        rows.append(row)
    return rows


def _already_migrated(source_table: str, source_ids: list[str]) -> set[str]:
    if not source_ids:
        return set()
    existing = ImageSourceMap.objects.filter(
        source_table=source_table,
        source_id__in=source_ids,
    ).values_list("source_id", flat=True)
    return set(existing)


def count_migration_candidates(source_id: int) -> dict:
    source = _load_source(source_id)
    _validate_source_config(source)

    migrated = ImageSourceMap.objects.filter(source_table=source.source_table).count()

    with db_alias_session(source.db_alias):
        conn = connections[source.db_alias]
        table = _quote_ident(source.source_table)
        blob = _quote_ident(source.blob_column)
        where_parts = [f"{blob} IS NOT NULL"]
        extra = validate_where_clause(source.where_clause)
        if extra:
            where_parts.append(f"({extra})")
        if conn.vendor == "mysql":
            where_parts.append(f"LENGTH({blob}) > 0")
        else:
            where_parts.append(f"length({blob}) > 0")

        sql = f"SELECT COUNT(*) FROM {table} WHERE {' AND '.join(where_parts)}"
        with conn.cursor() as cursor:
            cursor.execute(sql)
            total_with_blob = int(cursor.fetchone()[0])

    return {
        "source_id": source.id,
        "source_table": source.source_table,
        "db_alias": source.db_alias,
        "total_with_blob": total_with_blob,
        "migrated": migrated,
        "pending": max(total_with_blob - migrated, 0),
    }


def run_blob_migration(
    source_id: int,
    *,
    batch_size: int = 50,
    dry_run: bool = False,
    skip_existing: bool = True,
    upload_user: str | None = None,
) -> MigrationRunResult:
    source = _load_source(source_id)
    _validate_source_config(source)

    if batch_size <= 0:
        raise BlobMigrationError("batch_size 必须大于 0")
    batch_size = min(batch_size, 500)

    result = MigrationRunResult(
        source_id=source.id,
        source_table=source.source_table,
        dry_run=dry_run,
    )

    migrated_ids = set(
        ImageSourceMap.objects.filter(source_table=source.source_table).values_list("source_id", flat=True)
    )
    offset = 0
    actor = upload_user or source.upload_user or "migration"

    with db_alias_session(source.db_alias):
        while result.processed < batch_size:
            fetch_size = batch_size - result.processed
            rows = _fetch_source_rows(source, limit=max(fetch_size * 3, fetch_size), offset=offset)
            if not rows:
                break
            offset += len(rows)

            pk_col = source.source_pk_column
            pending_rows = []
            for row in rows:
                source_id_str = str(row[pk_col])
                if skip_existing and source_id_str in migrated_ids:
                    continue
                pending_rows.append(row)
                if len(pending_rows) >= fetch_size:
                    break

            if not pending_rows:
                continue

            result.total_candidates += len(pending_rows)

            for row in pending_rows:
                if result.processed >= batch_size:
                    break

                source_id_str = str(row[pk_col])
                result.processed += 1

                if skip_existing and source_id_str in migrated_ids:
                    result.skipped += 1
                    result.items.append(
                        MigrationItemResult(source_id=source_id_str, success=True, skipped=True)
                    )
                    continue

                try:
                    content = _coerce_blob(row[source.blob_column])
                    if not content:
                        raise BlobMigrationError("BLOB 为空")

                    name_value = row.get(source.name_column) if source.name_column else None
                    suffix_value = row.get(source.suffix_column) if source.suffix_column else None
                    filename = _infer_filename(
                        source_id=source_id_str,
                        content=content,
                        name_value=str(name_value) if name_value is not None else None,
                        suffix_value=str(suffix_value) if suffix_value is not None else None,
                        source_table=source.source_table,
                    )

                    if dry_run:
                        result.succeeded += 1
                        result.items.append(
                            MigrationItemResult(
                                source_id=source_id_str,
                                success=True,
                                filename=filename,
                            )
                        )
                        continue

                    image = save_image_bytes(
                        filename=filename,
                        content=content,
                        upload_user=actor,
                        category_id=source.category_id,
                        tags=source.tags,
                        overwrite=False,
                    )
                    ImageSourceMap.objects.create(
                        source_table=source.source_table,
                        source_id=source_id_str,
                        image_info_id=image.id,
                        migrated_at=timezone.now(),
                    )
                    migrated_ids.add(source_id_str)
                    result.succeeded += 1
                    result.items.append(
                        MigrationItemResult(
                            source_id=source_id_str,
                            success=True,
                            image_info_id=image.id,
                            filename=filename,
                        )
                    )
                except DuplicateImageError as exc:
                    if dry_run:
                        result.skipped += 1
                        result.items.append(
                            MigrationItemResult(
                                source_id=source_id_str,
                                success=True,
                                skipped=True,
                                filename=getattr(exc, "filename", ""),
                                error="已存在相同图片",
                            )
                        )
                    else:
                        existing = exc.existing
                        ImageSourceMap.objects.create(
                            source_table=source.source_table,
                            source_id=source_id_str,
                            image_info_id=existing.id,
                            migrated_at=timezone.now(),
                        )
                        migrated_ids.add(source_id_str)
                        result.skipped += 1
                        result.items.append(
                            MigrationItemResult(
                                source_id=source_id_str,
                                success=True,
                                skipped=True,
                                image_info_id=existing.id,
                                filename=getattr(exc, "filename", ""),
                                error="已存在相同图片，已建立映射",
                            )
                        )
                except Exception as exc:
                    result.failed += 1
                    logger.exception(
                        "blob migration failed source=%s id=%s",
                        source.source_table,
                        source_id_str,
                    )
                    result.items.append(
                        MigrationItemResult(
                            source_id=source_id_str,
                            success=False,
                            error=str(exc),
                        )
                    )

    if not dry_run:
        BlobMigrationSource.objects.filter(pk=source.pk).update(last_run_at=timezone.now())

    return result


def create_migration_source(**fields) -> BlobMigrationSource:
    source = BlobMigrationSource(
        name=fields.get("name", ""),
        source_table=fields["source_table"],
        source_pk_column=fields.get("source_pk_column") or "id",
        blob_column=fields["blob_column"],
        name_column=fields.get("name_column") or "",
        suffix_column=fields.get("suffix_column") or "",
        category_id=fields["category_id"],
        upload_user=fields.get("upload_user") or "migration",
        tags=(fields.get("tags") or "")[:500],
        where_clause=fields.get("where_clause") or "",
        db_alias=fields.get("db_alias") or "default",
        enabled=1,
        create_time=timezone.now(),
    )
    _validate_source_config(source)
    source.save(force_insert=True)
    return source
