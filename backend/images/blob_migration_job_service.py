"""Background BLOB migration jobs — create, run, progress, retry, export."""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from images.blob_migration_service import (
    BlobMigrationError,
    count_migration_candidates,
    execute_migration_job_batches,
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
    warm_thumbs_after: bool = False,
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

    stats = count_migration_candidates(source_id)
    total_estimate = stats["pending"] if skip_existing else stats["total_with_blob"]
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
        message="用户请求取消",
        updated_at=now,
    )
    job.refresh_from_db()
    return job


def list_migration_jobs(*, source_id: int | None = None, limit: int = 50) -> list[BlobMigrationJob]:
    qs = BlobMigrationJob.objects.all().order_by("-id")
    if source_id:
        qs = qs.filter(source_id=source_id)
    return list(qs[: max(1, min(limit, 200))])


def _compute_eta_seconds(job: BlobMigrationJob) -> int | None:
    if job.status != BlobMigrationJob.STATUS_RUNNING or not job.started_at or job.processed <= 0:
        return None
    elapsed = (timezone.now() - job.started_at).total_seconds()
    if elapsed <= 0:
        return None
    rate = job.processed / elapsed
    if rate <= 0:
        return None
    remaining = max(0, int(job.total_estimate) - int(job.processed))
    return int(remaining / rate) if remaining else 0


def serialize_migration_job(job: BlobMigrationJob, *, include_recent_errors: bool = True) -> dict[str, Any]:
    total = max(int(job.total_estimate or 0), int(job.processed or 0))
    percent = round(100.0 * job.processed / total, 2) if total else 0.0
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
        "processed": job.processed,
        "succeeded": job.succeeded,
        "failed": job.failed,
        "skipped": job.skipped,
        "percent": percent,
        "eta_seconds": _compute_eta_seconds(job),
        "message": job.message,
        "created_by": job.created_by,
        "started_at": job.started_at.isoformat(sep=" ", timespec="seconds") if job.started_at else None,
        "finished_at": job.finished_at.isoformat(sep=" ", timespec="seconds") if job.finished_at else None,
        "updated_at": job.updated_at.isoformat(sep=" ", timespec="seconds") if job.updated_at else None,
        "create_time": job.create_time.isoformat(sep=" ", timespec="seconds") if job.create_time else None,
    }
    if include_recent_errors:
        errors = BlobMigrationJobError.objects.filter(job_id=job.id).order_by("-id")[:20]
        payload["recent_errors"] = [
            {
                "source_pk": err.source_pk,
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
    writer.writerow(["source_pk", "filename", "error", "retried", "create_time"])
    for err in BlobMigrationJobError.objects.filter(job_id=job_id).order_by("id").iterator():
        writer.writerow(
            [
                err.source_pk,
                err.filename,
                err.error_message,
                err.retried,
                err.create_time.isoformat(sep=" ", timespec="seconds") if err.create_time else "",
            ]
        )
    return output.getvalue()


def _warm_thumbnails_after_job(job: BlobMigrationJob) -> None:
    if not job.warm_thumbs_after or job.dry_run:
        return
    from images.file_service import ImageNotFoundError, get_or_create_thumbnail
    from images.models import ImageInfo

    warmed = 0
    for image in ImageInfo.objects.filter(is_delete=0).order_by("id").iterator(chunk_size=200):
        try:
            get_or_create_thumbnail(image.image_path)
            warmed += 1
        except ImageNotFoundError:
            continue
        except Exception:
            logger.warning("warm thumb failed path=%s", image.image_path, exc_info=True)
    BlobMigrationJob.objects.filter(pk=job.pk).update(
        message=f"{job.message or '完成'}；已预热 {warmed} 张缩略图",
        updated_at=timezone.now(),
    )


def execute_migration_job(job_id: int) -> BlobMigrationJob:
    job = _load_job(job_id)
    if job.status not in {BlobMigrationJob.STATUS_PENDING, BlobMigrationJob.STATUS_RUNNING}:
        return job

    now = timezone.now()
    if job.status == BlobMigrationJob.STATUS_PENDING:
        BlobMigrationJob.objects.filter(pk=job.pk).update(
            status=BlobMigrationJob.STATUS_RUNNING,
            started_at=now,
            updated_at=now,
            message="迁移进行中",
        )
        job.refresh_from_db()

    try:
        if job.retry_failed_only:
            retry_failed_rows_for_job(job)
        else:
            execute_migration_job_batches(job)
        job.refresh_from_db()
        if job.cancel_requested:
            BlobMigrationJob.objects.filter(pk=job.pk).update(
                status=BlobMigrationJob.STATUS_CANCELLED,
                finished_at=timezone.now(),
                message=job.message or "已取消",
                updated_at=timezone.now(),
            )
        elif job.status == BlobMigrationJob.STATUS_RUNNING:
            _warm_thumbnails_after_job(job)
            job.refresh_from_db()
            BlobMigrationJob.objects.filter(pk=job.pk).update(
                status=BlobMigrationJob.STATUS_COMPLETED,
                finished_at=timezone.now(),
                message=job.message or "迁移完成",
                updated_at=timezone.now(),
            )
    except Exception as exc:
        logger.exception("migration job failed id=%s", job_id)
        BlobMigrationJob.objects.filter(pk=job.pk).update(
            status=BlobMigrationJob.STATUS_FAILED,
            finished_at=timezone.now(),
            message=str(exc)[:500],
            updated_at=timezone.now(),
        )

    return _load_job(job_id)


def process_pending_migration_jobs(*, max_jobs: int = 1) -> int:
    """Claim and run up to max_jobs pending jobs. Returns count started."""
    started = 0
    pending = BlobMigrationJob.objects.filter(status=BlobMigrationJob.STATUS_PENDING).order_by("id")
    for job in pending[: max(1, max_jobs)]:
        with transaction.atomic():
            locked = (
                BlobMigrationJob.objects.select_for_update()
                .filter(pk=job.pk, status=BlobMigrationJob.STATUS_PENDING)
                .first()
            )
            if not locked:
                continue
        execute_migration_job(locked.id)
        started += 1
    return started
