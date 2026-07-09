"""Background BLOB migration jobs — create, run, progress, retry, export."""
from __future__ import annotations

import csv
import io
import logging
import sys
import threading
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from images.blob_migration_service import (
    BlobMigrationError,
    count_migration_candidates,
    execute_migration_job_batches,
    prepare_migration_source,
    retry_failed_rows_for_job,
)
from images.models import BlobMigrationJob, BlobMigrationJobError, BlobMigrationSource

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = frozenset({BlobMigrationJob.STATUS_PENDING, BlobMigrationJob.STATUS_RUNNING})


class JobServiceError(Exception):
    pass


def _clamp_batch_size(value: int) -> int:
    max_batch = max(1, int(getattr(settings, "BLOB_MIGRATION_BATCH_MAX", 500)))
    return max(1, min(int(value or 50), max_batch))


def _load_job(job_id: int) -> BlobMigrationJob:
    try:
        return BlobMigrationJob.objects.get(pk=job_id)
    except BlobMigrationJob.DoesNotExist as exc:
        raise JobServiceError(f"任务不存在: id={job_id}") from exc


def _load_source(source_id: int) -> BlobMigrationSource:
    try:
        return BlobMigrationSource.objects.get(pk=source_id)
    except BlobMigrationSource.DoesNotExist as exc:
        raise JobServiceError(f"迁移配置不存在: id={source_id}") from exc


def _assert_no_active_job(source_id: int, *, exclude_job_id: int | None = None) -> None:
    qs = BlobMigrationJob.objects.filter(source_id=source_id, status__in=ACTIVE_STATUSES)
    if exclude_job_id:
        qs = qs.exclude(pk=exclude_job_id)
    if qs.exists():
        raise JobServiceError("该迁移源已有进行中的任务，请等待完成或取消后再试")


def create_migration_job(
    *,
    source_id: int,
    created_by: str,
    batch_size: int | None = None,
    dry_run: bool = False,
    skip_existing: bool = True,
    run_all: bool = True,
    warm_thumbs_after: bool = True,
    retry_failed_only: bool = False,
    parent_job_id: int | None = None,
) -> BlobMigrationJob:
    _load_source(source_id)
    if retry_failed_only:
        if not parent_job_id:
            raise JobServiceError("重试失败项须指定 parent_job_id")
        parent = _load_job(parent_job_id)
        if parent.failed <= 0 and not BlobMigrationJobError.objects.filter(
            job_id=parent_job_id, retried=0
        ).exists():
            raise JobServiceError("来源任务没有可重试的失败记录")
    else:
        _assert_no_active_job(source_id)

    # HTTP create returns immediately. Worker fills total_estimate for progress UI only.
    total_estimate = 0
    if retry_failed_only and parent_job_id:
        total_estimate = BlobMigrationJobError.objects.filter(job_id=parent_job_id, retried=0).count()

    now = timezone.now()
    job = BlobMigrationJob(
        source_id=source_id,
        status=BlobMigrationJob.STATUS_PENDING,
        dry_run=1 if dry_run else 0,
        skip_existing=1 if skip_existing else 0,
        run_all=1 if run_all else 0,
        retry_failed_only=1 if retry_failed_only else 0,
        parent_job_id=parent_job_id,
        batch_size=_clamp_batch_size(batch_size or settings.BLOB_MIGRATION_BATCH_SIZE),
        warm_thumbs_after=1 if warm_thumbs_after else 0,
        total_estimate=total_estimate,
        created_by=created_by or "migration",
        create_time=now,
        updated_at=now,
    )
    job.save(force_insert=True)
    return job


def cancel_migration_job(job_id: int) -> BlobMigrationJob:
    job = _load_job(job_id)
    if job.status in {BlobMigrationJob.STATUS_COMPLETED, BlobMigrationJob.STATUS_FAILED, BlobMigrationJob.STATUS_CANCELLED}:
        raise JobServiceError("任务已结束，无法取消")
    now = timezone.now()
    BlobMigrationJob.objects.filter(pk=job.pk).update(
        cancel_requested=1,
        status=BlobMigrationJob.STATUS_CANCELLED,
        finished_at=now,
        message="用户请求取消",
        updated_at=now,
    )
    job.refresh_from_db()
    return job


def delete_migration_job(job_id: int) -> None:
    job = _load_job(job_id)
    if job.status in ACTIVE_STATUSES:
        now = timezone.now()
        BlobMigrationJob.objects.filter(pk=job_id).update(
            cancel_requested=1,
            status=BlobMigrationJob.STATUS_CANCELLED,
            finished_at=now,
            message="强制删除",
            updated_at=now,
        )
    BlobMigrationJobError.objects.filter(job_id=job_id).delete()
    BlobMigrationJob.objects.filter(pk=job_id).delete()


def clear_migration_job_history(*, source_id: int | None = None) -> int:
    """Delete all migration jobs and their error rows (including stuck queue entries)."""
    qs = BlobMigrationJob.objects.all()
    if source_id is not None:
        qs = qs.filter(source_id=source_id)
    job_ids = list(qs.values_list("id", flat=True))
    if not job_ids:
        return 0
    BlobMigrationJobError.objects.filter(job_id__in=job_ids).delete()
    deleted, _ = BlobMigrationJob.objects.filter(pk__in=job_ids).delete()
    return deleted


def list_migration_jobs(*, source_id: int | None = None, limit: int = 50) -> list[BlobMigrationJob]:
    qs = BlobMigrationJob.objects.all().order_by("-id")
    if source_id:
        qs = qs.filter(source_id=source_id)
    return list(qs[: max(1, min(limit, 200))])


def _job_handled_count(job: BlobMigrationJob) -> int:
    return int(job.succeeded or 0) + int(job.failed or 0) + int(job.skipped or 0)


def _job_progress_count(job: BlobMigrationJob) -> int:
    """Success + fail rows (excludes skips) — used for ETA."""
    return int(job.succeeded or 0) + int(job.failed or 0)


def _job_progress_display(job: BlobMigrationJob) -> tuple[int, int, float]:
    """Return (done, total, percent) for API responses. total_estimate never gates execution."""
    handled = _job_handled_count(job)
    estimate = int(job.total_estimate or 0)

    if job.status in ACTIVE_STATUSES:
        done = handled
        total = max(estimate, done) if estimate > 0 else 0
        if total > 0:
            percent = min(99.0, round(100.0 * done / total, 2))
        else:
            percent = 0.0
        return done, total, percent

    done = handled
    total = max(estimate, done) if estimate > 0 else (done if done > 0 else 0)
    if job.status == BlobMigrationJob.STATUS_COMPLETED:
        percent = 100.0 if total > 0 or done == 0 else 100.0
    else:
        percent = 0.0
    return done, total, percent


def _compute_eta_seconds(job: BlobMigrationJob) -> int | None:
    progress_count = _job_progress_count(job)
    if job.status != BlobMigrationJob.STATUS_RUNNING or not job.started_at or progress_count <= 0:
        return None
    elapsed = (timezone.now() - job.started_at).total_seconds()
    if elapsed <= 0:
        return None
    rate = progress_count / elapsed
    if rate <= 0:
        return None
    estimate = int(job.total_estimate or 0)
    if estimate <= 0:
        return None
    remaining = max(0, estimate - progress_count)
    return int(remaining / rate) if remaining else 0


def serialize_migration_job(
    job: BlobMigrationJob,
    *,
    include_recent_errors: bool = True,
) -> dict[str, Any]:
    progress_count = _job_progress_count(job)
    display_done, display_total, display_percent = _job_progress_display(job)

    payload: dict[str, Any] = {
        "id": job.id,
        "source_id": job.source_id,
        "status": job.status,
        "dry_run": bool(job.dry_run),
        "skip_existing": bool(job.skip_existing),
        "run_all": bool(job.run_all),
        "retry_failed_only": bool(job.retry_failed_only),
        "parent_job_id": job.parent_job_id,
        "batch_size": job.batch_size,
        "warm_thumbs_after": bool(job.warm_thumbs_after),
        "cancel_requested": bool(job.cancel_requested),
        "total_estimate": job.total_estimate,
        "progress_count": progress_count,
        "processed": job.processed,
        "succeeded": job.succeeded,
        "failed": job.failed,
        "skipped": job.skipped,
        "percent": display_percent,
        "eta_seconds": _compute_eta_seconds(job),
        "message": job.message,
        "created_by": job.created_by,
        "started_at": job.started_at.isoformat(sep=" ", timespec="seconds") if job.started_at else None,
        "finished_at": job.finished_at.isoformat(sep=" ", timespec="seconds") if job.finished_at else None,
        "updated_at": job.updated_at.isoformat(sep=" ", timespec="seconds") if job.updated_at else None,
        "create_time": job.create_time.isoformat(sep=" ", timespec="seconds") if job.create_time else None,
        "display_done": display_done,
        "display_total": display_total,
    }
    if include_recent_errors:
        errors = BlobMigrationJobError.objects.filter(job_id=job.id).order_by("-id")[:20]
        payload["recent_errors"] = [
            {
                "source_pk": err.source_pk,
                "source_column": err.source_column or "",
                "filename": err.filename,
                "error": err.error_message,
                "retried": bool(err.retried),
            }
            for err in errors
        ]
        payload["error_count"] = BlobMigrationJobError.objects.filter(job_id=job.id).count()
    return payload


def export_job_errors_csv(job_id: int) -> str:
    _load_job(job_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["source_pk", "source_column", "filename", "error", "retried", "create_time"])
    for err in BlobMigrationJobError.objects.filter(job_id=job_id).order_by("id").iterator():
        writer.writerow(
            [
                err.source_pk,
                err.source_column or "",
                err.filename,
                err.error_message,
                err.retried,
                err.create_time.isoformat(sep=" ", timespec="seconds") if err.create_time else "",
            ]
        )
    return output.getvalue()


def _warm_thumbnails_after_job(job_id: int) -> None:
    job = _load_job(job_id)
    if not job.warm_thumbs_after or job.dry_run:
        return
    from images.blob_migration_service import _load_source, _storage_table
    from images.file_service import ImageNotFoundError, get_or_create_thumbnail
    from images.models import ImageInfo, ImageSourceMap

    source = _load_source(job.source_id)
    storage_table = _storage_table(source)
    map_qs = ImageSourceMap.objects.filter(source_table=storage_table)
    if job.started_at:
        map_qs = map_qs.filter(migrated_at__gte=job.started_at)

    image_ids = list(map_qs.values_list("image_info_id", flat=True).distinct())
    warmed = 0
    for image in ImageInfo.objects.filter(pk__in=image_ids, is_delete=0).iterator(chunk_size=200):
        if BlobMigrationJob.objects.filter(pk=job.pk, cancel_requested=1).exists():
            break
        try:
            get_or_create_thumbnail(image.image_path)
            warmed += 1
        except ImageNotFoundError:
            continue
        except Exception:
            logger.warning("warm thumb failed path=%s", image.image_path, exc_info=True)
    BlobMigrationJob.objects.filter(pk=job.pk).update(
        message=f"{_completion_message(job)}；已预热 {warmed} 张缩略图",
        updated_at=timezone.now(),
    )


def _run_warm_thumbnails_worker(job_id: int) -> None:
    from django.db import close_old_connections

    close_old_connections()
    try:
        _warm_thumbnails_after_job(job_id)
    except Exception:
        logger.exception("warm thumbnails worker failed job_id=%s", job_id)
    finally:
        close_old_connections()


def _kick_warm_thumbnails_async(job_id: int) -> None:
    thread = threading.Thread(
        target=_run_warm_thumbnails_worker,
        args=(job_id,),
        name=f"blob-migrate-warm-{job_id}",
        daemon=True,
    )
    thread.start()
    logger.info("kicked warm thumbnails thread job_id=%s", job_id)


def _completion_message(job: BlobMigrationJob) -> str:
    succeeded = int(job.succeeded or 0)
    skipped = int(job.skipped or 0)
    failed = int(job.failed or 0)
    handled = succeeded + skipped + failed
    estimate = int(job.total_estimate or 0)
    prior = (job.message or "").strip()
    # Keep empty-scan diagnostics from the runner.
    if handled == 0 and prior.startswith("源表扫描"):
        return prior
    if handled == 0 and estimate == 0:
        return "迁移完成：未发现可迁移数据"
    if estimate > 0:
        return (
            f"迁移完成（处理 {handled}/{estimate}："
            f"成功 {succeeded} · 跳过 {skipped} · 失败 {failed}）"
        )
    return f"迁移完成（成功 {succeeded} · 跳过 {skipped} · 失败 {failed}）"


def _refresh_job_estimate_for_ui(job: BlobMigrationJob) -> BlobMigrationJob:
    """Best-effort COUNT for the progress bar. Never affects whether batches run."""
    if job.retry_failed_only or int(job.total_estimate or 0) > 0:
        return job

    BlobMigrationJob.objects.filter(pk=job.pk, status=BlobMigrationJob.STATUS_RUNNING).update(
        message="正在统计待迁移数量…",
        updated_at=timezone.now(),
    )
    try:
        prepare_migration_source(_load_source(job.source_id))
        stats = count_migration_candidates(job.source_id, use_cache=True)
        if bool(job.skip_existing):
            estimate = int(stats.get("pending") or 0)
        else:
            estimate = int(stats.get("total_with_blob") or 0)
    except Exception:
        logger.warning(
            "count_migration_candidates failed job_id=%s source_id=%s",
            job.id,
            job.source_id,
            exc_info=True,
        )
        BlobMigrationJob.objects.filter(pk=job.pk).update(
            message="统计未完成，正在扫描迁移…",
            updated_at=timezone.now(),
        )
        job.refresh_from_db()
        return job

    BlobMigrationJob.objects.filter(pk=job.pk).update(
        total_estimate=max(0, estimate),
        message=f"迁移进行中（预估 {estimate}）" if estimate > 0 else "迁移进行中（扫描确认中）",
        updated_at=timezone.now(),
    )
    job.refresh_from_db()
    return job


def execute_migration_job(job_id: int) -> BlobMigrationJob:
    with transaction.atomic():
        job = (
            BlobMigrationJob.objects.select_for_update()
            .filter(
                pk=job_id,
                status__in={BlobMigrationJob.STATUS_PENDING, BlobMigrationJob.STATUS_RUNNING},
            )
            .first()
        )
        if not job:
            return _load_job(job_id)
        if job.cancel_requested or job.status == BlobMigrationJob.STATUS_CANCELLED:
            now = timezone.now()
            BlobMigrationJob.objects.filter(pk=job_id).update(
                status=BlobMigrationJob.STATUS_CANCELLED,
                finished_at=now,
                updated_at=now,
                message=job.message or "已取消",
            )
            return _load_job(job_id)
        if job.status == BlobMigrationJob.STATUS_PENDING:
            now = timezone.now()
            BlobMigrationJob.objects.filter(pk=job_id).update(
                status=BlobMigrationJob.STATUS_RUNNING,
                started_at=now,
                updated_at=now,
                message="迁移进行中",
            )

    job = _load_job(job_id)
    if job.status != BlobMigrationJob.STATUS_RUNNING or job.cancel_requested:
        return job

    try:
        if job.retry_failed_only:
            prepare_migration_source(_load_source(job.source_id))
            retry_failed_rows_for_job(job)
        else:
            prepare_migration_source(_load_source(job.source_id))
            job = _refresh_job_estimate_for_ui(job)
            if job.cancel_requested or job.status == BlobMigrationJob.STATUS_CANCELLED:
                return _load_job(job_id)
            execute_migration_job_batches(job)
        job.refresh_from_db()
        if job.cancel_requested or job.status == BlobMigrationJob.STATUS_CANCELLED:
            BlobMigrationJob.objects.filter(pk=job.pk).update(
                status=BlobMigrationJob.STATUS_CANCELLED,
                finished_at=timezone.now(),
                message=job.message or "已取消",
                updated_at=timezone.now(),
            )
        elif job.status == BlobMigrationJob.STATUS_RUNNING:
            job.refresh_from_db()
            done_message = _completion_message(job)
            BlobMigrationJob.objects.filter(pk=job.pk).update(
                status=BlobMigrationJob.STATUS_COMPLETED,
                finished_at=timezone.now(),
                message=done_message,
                updated_at=timezone.now(),
            )
            job.refresh_from_db()
            if job.warm_thumbs_after and int(job.succeeded or 0) > 0:
                _kick_warm_thumbnails_async(job.id)
    except Exception as exc:
        logger.exception("migration job failed id=%s", job_id)
        BlobMigrationJob.objects.filter(pk=job.pk).update(
            status=BlobMigrationJob.STATUS_FAILED,
            finished_at=timezone.now(),
            message=str(exc)[:500],
            updated_at=timezone.now(),
        )

    return _load_job(job_id)


def process_pending_migration_jobs(*, max_jobs: int = 1, job_id: int | None = None) -> int:
    """Claim and run pending jobs. Returns count started."""
    if job_id is not None:
        job = _load_job(job_id)
        if job.status not in ACTIVE_STATUSES:
            return 0
        execute_migration_job(job_id)
        return 1

    started = 0
    pending = BlobMigrationJob.objects.filter(status=BlobMigrationJob.STATUS_PENDING).order_by("id")
    for job in pending[: max(1, max_jobs)]:
        execute_migration_job(job.id)
        started += 1
    return started


def _run_migration_worker(job_id: int) -> None:
    from django.db import close_old_connections

    close_old_connections()
    try:
        execute_migration_job(job_id)
    except Exception:
        logger.exception("migration worker failed job_id=%s", job_id)
    finally:
        close_old_connections()


def _kick_migration_thread(job_id: int) -> None:
    thread = threading.Thread(
        target=_run_migration_worker,
        args=(job_id,),
        name=f"blob-migrate-{job_id}",
        daemon=True,
    )
    thread.start()
    logger.info("kicked migration worker thread job_id=%s", job_id)


def kick_migration_job_async(job_id: int) -> None:
    """Run migration in a background thread inside the backend container."""
    _kick_migration_thread(job_id)
