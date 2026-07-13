"""External BLOB sync: fingerprint backfill, change detection, auto re-migration."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db import connections
from django.utils import timezone

from images.blob_migration_service import (
    BlobMigrationError,
    _fetch_source_row_by_pk,
    _load_source,
    _migrate_row,
    _quote_ident,
    _source_db_session,
    prepare_migration_source,
    validate_identifier,
)
from images.blob_sync_constants import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_TYPE_BACKFILL,
    RUN_TYPE_DETECT,
    RUN_TYPE_RESYNC,
    SYNC_STATUS_CHANGED,
    SYNC_STATUS_ERROR,
    SYNC_STATUS_IN_SYNC,
    SYNC_STATUS_MISSING,
    SYNC_STATUS_PENDING_RESYNC,
    SYNC_STATUS_UNKNOWN,
)
from images.blob_sync_context import TableSyncContext, build_sync_context_index, resolve_sync_context
from images.blob_sync_detect import refresh_source_change_track
from images.external_db_service import db_alias_session
from images.models import BlobMigrationSource, BlobSyncRun, ImageInfo, ImageSourceMap
from images.purge_service import purge_image_record

logger = logging.getLogger(__name__)


class BlobSyncError(Exception):
    pass


@dataclass
class SyncBatchResult:
    checked: int = 0
    changed: int = 0
    resynced: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _normalize_hash(value: str | None) -> str:
    return (value or "").strip().lower()


def _use_mysql_sha2() -> bool:
    return bool(getattr(settings, "BLOB_SYNC_USE_MYSQL_SHA2", True))


def _purge_old_after_resync() -> bool:
    return bool(getattr(settings, "BLOB_SYNC_PURGE_OLD_IMAGE", True))


def _max_resync_per_run() -> int:
    return int(getattr(settings, "BLOB_SYNC_MAX_RESYNC_PER_RUN", 50))


def _sync_enabled_globally() -> bool:
    return bool(getattr(settings, "BLOB_SYNC_ENABLED", True))


def _quote_table(name: str) -> str:
    return _quote_ident(validate_identifier(name, label="源表名"))


def _quote_col(name: str) -> str:
    return _quote_ident(validate_identifier(name, label="列名"))


def fetch_remote_fingerprint(
    conn,
    ctx: TableSyncContext,
    source_id: str,
) -> tuple[int, str] | None:
    """Return (length, sha256_hex) or None when row missing."""
    table = _quote_table(ctx.lookup_table)
    pk = _quote_col(ctx.pk_column)
    blob = _quote_col(ctx.blob_column or ctx.source_column)
    sql = f"SELECT LENGTH({blob}), SHA2({blob}, 256) FROM {table} WHERE {pk} = %s LIMIT 1"
    with conn.cursor() as cursor:
        cursor.execute(sql, [source_id])
        row = cursor.fetchone()
    if not row:
        return None
    length = int(row[0] or 0)
    digest = _normalize_hash(str(row[1] or "") if row[1] is not None else "")
    if not digest and length > 0 and not _use_mysql_sha2():
        raise BlobSyncError("MySQL SHA2 unavailable and BLOB_SYNC_USE_MYSQL_SHA2=0")
    return length, digest


def fetch_remote_fingerprints_batch(
    conn,
    ctx: TableSyncContext,
    source_ids: list[str],
) -> dict[str, tuple[int, str] | None]:
    if not source_ids:
        return {}
    table = _quote_table(ctx.lookup_table)
    pk = _quote_col(ctx.pk_column)
    blob = _quote_col(ctx.blob_column or ctx.source_column)
    placeholders = ", ".join(["%s"] * len(source_ids))
    sql = (
        f"SELECT {pk}, LENGTH({blob}), SHA2({blob}, 256) "
        f"FROM {table} WHERE {pk} IN ({placeholders})"
    )
    results: dict[str, tuple[int, str] | None] = {sid: None for sid in source_ids}
    with conn.cursor() as cursor:
        cursor.execute(sql, source_ids)
        for pk_val, length, digest in cursor.fetchall():
            key = str(pk_val)
            results[key] = (int(length or 0), _normalize_hash(str(digest or "")))
    return results


def classify_sync_status(
    *,
    remote: tuple[int, str] | None,
    stored_hash: str,
    stored_length: int,
    local_file_hash: str,
) -> str:
    if remote is None:
        return SYNC_STATUS_MISSING
    length, digest = remote
    if stored_hash and digest == _normalize_hash(stored_hash):
        return SYNC_STATUS_IN_SYNC
    if not stored_hash and digest and _normalize_hash(local_file_hash) == digest:
        return SYNC_STATUS_IN_SYNC
    if stored_length and stored_length == length and stored_hash and digest != stored_hash:
        return SYNC_STATUS_CHANGED
    if not stored_hash and not local_file_hash:
        return SYNC_STATUS_UNKNOWN if digest else SYNC_STATUS_MISSING
    if digest and (_normalize_hash(local_file_hash) == digest):
        return SYNC_STATUS_IN_SYNC
    if digest:
        return SYNC_STATUS_CHANGED
    return SYNC_STATUS_MISSING


def update_map_fingerprint(
    map_row: ImageSourceMap,
    *,
    length: int,
    digest: str,
    status: str,
    error: str = "",
) -> None:
    ImageSourceMap.objects.filter(pk=map_row.pk).update(
        source_blob_length=length,
        source_content_hash=digest,
        sync_status=status,
        last_checked_at=timezone.now(),
        last_sync_error=(error or "")[:500],
    )


def _local_file_hash(image_info_id: int) -> str:
    try:
        image = ImageInfo.objects.get(pk=image_info_id, is_delete=0)
    except ImageInfo.DoesNotExist:
        return ""
    return _normalize_hash(image.file_hash or "")


def _maps_for_source(source: BlobMigrationSource) -> list[int]:
    from images.blob_sync_context import _source_lookup_tables

    tables = _source_lookup_tables(source)
    if not tables:
        return []
    return list(
        ImageSourceMap.objects.filter(source_table__in=tables)
        .order_by("id")
        .values_list("id", flat=True)
    )


def _load_map(pk: int) -> ImageSourceMap:
    return ImageSourceMap.objects.get(pk=pk)


def process_map_fingerprint(
    map_row: ImageSourceMap,
    *,
    ctx: TableSyncContext,
    conn,
    index=None,
) -> str:
    if ctx is None:
        ctx = resolve_sync_context(map_row.source_table, map_row.source_column, index=index)
    if ctx is None:
        update_map_fingerprint(
            map_row,
            length=0,
            digest="",
            status=SYNC_STATUS_ERROR,
            error="无法解析同步上下文（缺少迁移源/连接配置）",
        )
        return SYNC_STATUS_ERROR
    try:
        remote = fetch_remote_fingerprint(conn, ctx, map_row.source_id)
    except Exception as exc:
        update_map_fingerprint(
            map_row,
            length=map_row.source_blob_length or 0,
            digest=map_row.source_content_hash or "",
            status=SYNC_STATUS_ERROR,
            error=str(exc),
        )
        return SYNC_STATUS_ERROR

    local_hash = _local_file_hash(map_row.image_info_id)
    status = classify_sync_status(
        remote=remote,
        stored_hash=map_row.source_content_hash or "",
        stored_length=int(map_row.source_blob_length or 0),
        local_file_hash=local_hash,
    )
    if remote is None:
        update_map_fingerprint(map_row, length=0, digest="", status=status)
    else:
        length, digest = remote
        update_map_fingerprint(map_row, length=length, digest=digest, status=status)
    return status


def resync_map_row(
    map_row: ImageSourceMap,
    source: BlobMigrationSource,
    *,
    actor: str = "blob_sync",
) -> bool:
    old_image_id = map_row.image_info_id
    row = _fetch_source_row_by_pk(source, map_row.source_id)
    if row is None:
        update_map_fingerprint(
            map_row,
            length=0,
            digest="",
            status=SYNC_STATUS_MISSING,
            error="源表记录不存在",
        )
        return False

    blob_col = (map_row.source_column or "").strip() or None
    try:
        results = _migrate_row(
            source,
            row,
            actor=actor,
            dry_run=False,
            skip_existing=False,
            blob_column=blob_col,
        )
    except Exception as exc:
        update_map_fingerprint(
            map_row,
            length=int(map_row.source_blob_length or 0),
            digest=map_row.source_content_hash or "",
            status=SYNC_STATUS_ERROR,
            error=str(exc),
        )
        return False

    success = any(r.success and not r.skipped for r in results)
    if not success:
        err = next((r.error for r in results if r.error), "重迁失败")
        update_map_fingerprint(
            map_row,
            length=int(map_row.source_blob_length or 0),
            digest=map_row.source_content_hash or "",
            status=SYNC_STATUS_ERROR,
            error=err or "重迁失败",
        )
        return False

    if _purge_old_after_resync() and old_image_id:
        try:
            old = ImageInfo.objects.get(pk=old_image_id)
            if old.is_delete == 0:
                purge_image_record(old)
        except ImageInfo.DoesNotExist:
            pass
        except Exception:
            logger.warning("purge old image after resync id=%s failed", old_image_id, exc_info=True)

    refreshed = _load_map(map_row.pk)
    ctx = resolve_sync_context(refreshed.source_table, refreshed.source_column)
    if ctx:
        with db_alias_session(ctx.db_alias, database=ctx.database_name or None) as alias:
            conn = connections[alias]
            process_map_fingerprint(refreshed, ctx=ctx, conn=conn)
    return True


def _resolve_source_for_map(map_row: ImageSourceMap, ctx: TableSyncContext) -> BlobMigrationSource | None:
    if ctx.migration_source_id:
        try:
            return prepare_migration_source(_load_source(ctx.migration_source_id))
        except BlobMigrationError:
            pass

    from images.blob_sync_context import _source_lookup_tables

    lookup = (map_row.source_table or "").strip()
    for source in BlobMigrationSource.objects.filter(enabled=1).order_by("id"):
        if lookup in _source_lookup_tables(source):
            try:
                return prepare_migration_source(source)
            except BlobMigrationError:
                continue
    return None


def backfill_source_sync_fingerprints(
    *,
    source_id: int | None = None,
    lookup_table: str | None = None,
    batch_size: int | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> SyncBatchResult:
    batch_size = batch_size or int(getattr(settings, "BLOB_SYNC_BATCH_SIZE", 200))
    result = SyncBatchResult()
    index = build_sync_context_index()

    qs = ImageSourceMap.objects.all().order_by("id")
    if source_id is not None:
        try:
            source = _load_source(source_id)
        except BlobMigrationError as exc:
            raise BlobSyncError(str(exc)) from exc
        map_ids = _maps_for_source(source)
        qs = qs.filter(id__in=map_ids)
    if lookup_table:
        qs = qs.filter(source_table=lookup_table)
    if limit:
        qs = qs[:limit]

    run = None
    if not dry_run:
        run = BlobSyncRun.objects.create(
            source_id=source_id,
            run_type=RUN_TYPE_BACKFILL,
            status=RUN_STATUS_RUNNING,
            started_at=timezone.now(),
        )

    grouped: dict[tuple[str, str], list[ImageSourceMap]] = {}
    for map_row in qs.iterator(chunk_size=batch_size):
        key = (map_row.source_table, map_row.source_column or "")
        grouped.setdefault(key, []).append(map_row)

    try:
        for (table, col), rows in grouped.items():
            ctx = resolve_sync_context(table, col, index=index)
            if ctx is None:
                for map_row in rows:
                    result.checked += 1
                    result.failed += 1
                    if not dry_run:
                        update_map_fingerprint(
                            map_row,
                            length=0,
                            digest="",
                            status=SYNC_STATUS_ERROR,
                            error="无法解析同步上下文",
                        )
                continue
            with db_alias_session(ctx.db_alias, database=ctx.database_name or None) as alias:
                conn = connections[alias]
                for offset in range(0, len(rows), batch_size):
                    chunk = rows[offset : offset + batch_size]
                    ids = [r.source_id for r in chunk]
                    try:
                        remote_map = fetch_remote_fingerprints_batch(conn, ctx, ids)
                    except Exception as exc:
                        result.failed += len(chunk)
                        result.errors.append(f"{table}: {exc}")
                        if not dry_run:
                            for map_row in chunk:
                                update_map_fingerprint(
                                    map_row,
                                    length=0,
                                    digest="",
                                    status=SYNC_STATUS_ERROR,
                                    error=str(exc),
                                )
                        continue
                    for map_row in chunk:
                        result.checked += 1
                        remote = remote_map.get(map_row.source_id)
                        local_hash = _local_file_hash(map_row.image_info_id)
                        status = classify_sync_status(
                            remote=remote,
                            stored_hash=map_row.source_content_hash or "",
                            stored_length=int(map_row.source_blob_length or 0),
                            local_file_hash=local_hash,
                        )
                        if status == SYNC_STATUS_CHANGED:
                            result.changed += 1
                        if remote is None:
                            if not dry_run:
                                update_map_fingerprint(map_row, length=0, digest="", status=status)
                            continue
                        length, digest = remote
                        if not dry_run:
                            update_map_fingerprint(map_row, length=length, digest=digest, status=status)
        if run:
            BlobSyncRun.objects.filter(pk=run.pk).update(
                status=RUN_STATUS_COMPLETED,
                checked=result.checked,
                changed=result.changed,
                failed=result.failed,
                finished_at=timezone.now(),
                message="backfill complete",
            )
    except Exception as exc:
        if run:
            BlobSyncRun.objects.filter(pk=run.pk).update(
                status=RUN_STATUS_FAILED,
                checked=result.checked,
                changed=result.changed,
                failed=result.failed,
                finished_at=timezone.now(),
                message=str(exc)[:500],
            )
        raise
    return result


def run_detect_and_resync_for_source(source_id: int, *, actor: str = "blob_sync") -> SyncBatchResult:
    if not _sync_enabled_globally():
        return SyncBatchResult()

    source = prepare_migration_source(_load_source(source_id))
    batch_size = int(getattr(source, "sync_batch_size", 0) or 0) or int(
        getattr(settings, "BLOB_SYNC_BATCH_SIZE", 200)
    )

    with _source_db_session(source) as alias:
        refresh_source_change_track(source, conn_alias=alias)

    result = SyncBatchResult()
    run = BlobSyncRun.objects.create(
        source_id=source_id,
        run_type=RUN_TYPE_DETECT,
        status=RUN_STATUS_RUNNING,
        started_at=timezone.now(),
    )

    index = build_sync_context_index()
    cursor_id = int(getattr(source, "sync_last_checked_map_id", 0) or 0)
    map_ids = [mid for mid in _maps_for_source(source) if mid > cursor_id]
    if not map_ids:
        map_ids = _maps_for_source(source)
        cursor_id = 0

    resync_budget = _max_resync_per_run()

    try:
        for map_id in map_ids[:batch_size]:
            map_row = _load_map(map_id)
            ctx = resolve_sync_context(map_row.source_table, map_row.source_column, index=index)
            if ctx is None:
                result.checked += 1
                result.failed += 1
                update_map_fingerprint(
                    map_row,
                    length=0,
                    digest="",
                    status=SYNC_STATUS_ERROR,
                    error="无法解析同步上下文",
                )
                continue
            with db_alias_session(ctx.db_alias, database=ctx.database_name or None) as alias:
                conn = connections[alias]
                status = process_map_fingerprint(map_row, ctx=ctx, conn=conn, index=index)
            result.checked += 1
            if status == SYNC_STATUS_CHANGED:
                result.changed += 1
                if resync_budget > 0:
                    mig_source = _resolve_source_for_map(map_row, ctx)
                    if mig_source is None:
                        update_map_fingerprint(
                            _load_map(map_row.pk),
                            length=int(map_row.source_blob_length or 0),
                            digest=map_row.source_content_hash or "",
                            status=SYNC_STATUS_PENDING_RESYNC,
                            error="已检测到变更，但未配置迁移源，无法自动重迁",
                        )
                        result.failed += 1
                    elif resync_map_row(_load_map(map_row.pk), mig_source, actor=actor):
                        result.resynced += 1
                        resync_budget -= 1
                    else:
                        result.failed += 1

            cursor_id = map_id

        next_cursor = cursor_id if map_ids else 0
        if len(map_ids) <= batch_size:
            next_cursor = 0

        now = timezone.now()
        BlobMigrationSource.objects.filter(pk=source_id).update(
            sync_last_run_at=now,
            sync_last_checked_map_id=next_cursor,
        )
        BlobSyncRun.objects.filter(pk=run.pk).update(
            status=RUN_STATUS_COMPLETED,
            checked=result.checked,
            changed=result.changed,
            resynced=result.resynced,
            failed=result.failed,
            finished_at=now,
            message=f"cursor={next_cursor}",
        )
    except Exception as exc:
        BlobSyncRun.objects.filter(pk=run.pk).update(
            status=RUN_STATUS_FAILED,
            checked=result.checked,
            changed=result.changed,
            resynced=result.resynced,
            failed=result.failed,
            finished_at=timezone.now(),
            message=str(exc)[:500],
        )
        raise
    return result


def source_sync_due(source: BlobMigrationSource) -> bool:
    if not _sync_enabled_globally():
        return False
    if not int(getattr(source, "auto_sync_enabled", 0) or 0):
        return False
    interval = int(getattr(source, "sync_interval_minutes", 0) or 0) or int(
        getattr(settings, "BLOB_SYNC_DEFAULT_INTERVAL_MINUTES", 60)
    )
    last = getattr(source, "sync_last_run_at", None)
    if last is None:
        return True
    return timezone.now() >= last + timedelta(minutes=interval)


def process_due_blob_sync(*, max_sources: int = 1) -> int:
    """Run detect+resync for due migration sources. Returns count processed."""
    if not _sync_enabled_globally():
        return 0
    processed = 0
    for source in BlobMigrationSource.objects.filter(enabled=1, auto_sync_enabled=1).order_by("id"):
        if processed >= max_sources:
            break
        if not source_sync_due(source):
            continue
        try:
            run_detect_and_resync_for_source(source.id)
            processed += 1
        except Exception:
            logger.warning("blob sync failed source_id=%s", source.id, exc_info=True)
    return processed


def count_sync_stats(source_id: int | None = None) -> dict[str, int]:
    qs = ImageSourceMap.objects.all()
    if source_id is not None:
        source = _load_source(source_id)
        map_ids = _maps_for_source(source)
        qs = qs.filter(id__in=map_ids)
    stats = {
        SYNC_STATUS_UNKNOWN: 0,
        SYNC_STATUS_IN_SYNC: 0,
        SYNC_STATUS_CHANGED: 0,
        SYNC_STATUS_MISSING: 0,
        SYNC_STATUS_ERROR: 0,
        SYNC_STATUS_PENDING_RESYNC: 0,
    }
    for row in qs.values("sync_status").iterator():
        status = (row.get("sync_status") or SYNC_STATUS_UNKNOWN).strip() or SYNC_STATUS_UNKNOWN
        stats[status] = stats.get(status, 0) + 1
    stats["total"] = qs.count()
    return stats
