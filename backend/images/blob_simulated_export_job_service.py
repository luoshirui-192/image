"""Background jobs for simulated table export (avoid gateway 504 on long sync POST)."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from images.blob_simulated_export_service import (
    SimulatedExportCancelled,
    SimulatedExportError,
    SimulatedExportPaused,
    export_simulated_table_to_connection,
)
from images.models import BlobSimulatedExportJob
from utils.db_time import fetch_db_now

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = frozenset(
    {
        BlobSimulatedExportJob.STATUS_PENDING,
        BlobSimulatedExportJob.STATUS_RUNNING,
    }
)


def _parse_result_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def serialize_export_job(job: BlobSimulatedExportJob) -> dict[str, Any]:
    total = int(job.total_estimate or 0)
    done = int(job.rows_written or 0)
    if job.status == BlobSimulatedExportJob.STATUS_COMPLETED:
        percent = 100.0
    elif total > 0:
        percent = min(99.0, round(100.0 * done / total, 2))
    elif job.status == BlobSimulatedExportJob.STATUS_RUNNING:
        percent = 5.0
    else:
        percent = 0.0
    result = _parse_result_json(job.result_json)
    return {
        "id": job.id,
        "view_id": job.view_id,
        "target_connection_id": job.target_connection_id,
        "target_db_alias": job.target_db_alias,
        "target_database": job.target_database,
        "target_table": job.target_table,
        "if_exists": job.if_exists,
        "status": job.status,
        "total_estimate": total,
        "rows_written": done,
        "last_offset": int(getattr(job, "last_offset", 0) or 0),
        "percent": percent,
        "cancel_requested": bool(job.cancel_requested),
        "pause_requested": bool(getattr(job, "pause_requested", 0)),
        "message": job.message,
        "last_error": job.last_error,
        "result": result or None,
        "created_by": job.created_by,
        "create_time": job.create_time.isoformat(sep=" ") if job.create_time else None,
        "started_at": job.started_at.isoformat(sep=" ") if job.started_at else None,
        "finished_at": job.finished_at.isoformat(sep=" ") if job.finished_at else None,
        "updated_at": job.updated_at.isoformat(sep=" ") if job.updated_at else None,
    }


def create_export_job(
    *,
    view_id: int,
    created_by: str = "",
    target_connection_id: int | None = None,
    target_db_alias: str = "",
    target_database: str = "",
    target_table: str = "",
    if_exists: str = "fail",
) -> BlobSimulatedExportJob:
    now = fetch_db_now()
    job = BlobSimulatedExportJob(
        view_id=view_id,
        target_connection_id=target_connection_id,
        target_db_alias=(target_db_alias or "")[:64],
        target_database=(target_database or "")[:64],
        target_table=(target_table or "")[:64],
        if_exists=(if_exists or "fail")[:20],
        status=BlobSimulatedExportJob.STATUS_PENDING,
        last_offset=0,
        rows_written=0,
        message="排队中…",
        created_by=(created_by or "")[:100],
        create_time=now,
        updated_at=now,
    )
    job.save()
    return job


def cancel_export_job(job_id: int) -> BlobSimulatedExportJob:
    job = BlobSimulatedExportJob.objects.filter(pk=job_id).first()
    if not job:
        raise SimulatedExportError("导出任务不存在")
    if job.status in {
        BlobSimulatedExportJob.STATUS_COMPLETED,
        BlobSimulatedExportJob.STATUS_FAILED,
        BlobSimulatedExportJob.STATUS_CANCELLED,
    }:
        return job
    now = timezone.now()
    BlobSimulatedExportJob.objects.filter(pk=job.pk).update(
        cancel_requested=1,
        pause_requested=0,
        updated_at=now,
        message="正在取消…",
    )
    if job.status in {
        BlobSimulatedExportJob.STATUS_PENDING,
        BlobSimulatedExportJob.STATUS_PAUSED,
    }:
        BlobSimulatedExportJob.objects.filter(pk=job.pk).update(
            status=BlobSimulatedExportJob.STATUS_CANCELLED,
            finished_at=now,
            message="已取消",
        )
        kick_export_queue()
    return BlobSimulatedExportJob.objects.get(pk=job.pk)


def pause_export_job(job_id: int) -> BlobSimulatedExportJob:
    job = BlobSimulatedExportJob.objects.filter(pk=job_id).first()
    if not job:
        raise SimulatedExportError("导出任务不存在")
    if job.status not in {
        BlobSimulatedExportJob.STATUS_PENDING,
        BlobSimulatedExportJob.STATUS_RUNNING,
    }:
        raise SimulatedExportError("只能暂停排队中或进行中的导出任务")
    now = timezone.now()
    if job.status == BlobSimulatedExportJob.STATUS_PENDING:
        BlobSimulatedExportJob.objects.filter(pk=job.pk).update(
            status=BlobSimulatedExportJob.STATUS_PAUSED,
            pause_requested=0,
            cancel_requested=0,
            message="已暂停（尚未开始）",
            updated_at=now,
        )
        # Pause holds the queue slot — do not auto-start the next job.
    else:
        BlobSimulatedExportJob.objects.filter(pk=job.pk).update(
            pause_requested=1,
            cancel_requested=0,
            message="正在暂停…",
            updated_at=now,
        )
    return BlobSimulatedExportJob.objects.get(pk=job.pk)


def resume_export_job(job_id: int) -> BlobSimulatedExportJob:
    job = BlobSimulatedExportJob.objects.filter(pk=job_id).first()
    if not job:
        raise SimulatedExportError("导出任务不存在")
    if job.status != BlobSimulatedExportJob.STATUS_PAUSED:
        raise SimulatedExportError("只能继续已暂停的导出任务")
    now = timezone.now()
    BlobSimulatedExportJob.objects.filter(pk=job.pk).update(
        status=BlobSimulatedExportJob.STATUS_PENDING,
        pause_requested=0,
        cancel_requested=0,
        finished_at=None,
        message="已排队，等待继续…",
        updated_at=now,
    )
    kick_export_job_async(job.pk)
    kick_export_queue()
    return BlobSimulatedExportJob.objects.get(pk=job.pk)


def reclaim_orphaned_export_jobs(
    *,
    reason: str = "服务重启，已自动重新排队",
    include_paused: bool = False,
) -> int:
    """Mark orphaned running (and optionally paused) exports as pending for resume."""
    statuses = [BlobSimulatedExportJob.STATUS_RUNNING]
    if include_paused:
        statuses.append(BlobSimulatedExportJob.STATUS_PAUSED)
    reclaim_ids = list(
        BlobSimulatedExportJob.objects.filter(status__in=statuses).values_list("id", flat=True)
    )
    if not reclaim_ids:
        return 0
    return _reclaim_export_ids(reclaim_ids, reason=reason)


def reclaim_stale_running_export_jobs(*, stale_seconds: int = 180) -> int:
    """Re-queue RUNNING exports with no progress heartbeat (worker/thread died)."""
    from datetime import timedelta

    from django.db.models import Q

    stale_seconds = max(30, int(stale_seconds or 180))
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    ids = list(
        BlobSimulatedExportJob.objects.filter(status=BlobSimulatedExportJob.STATUS_RUNNING)
        .filter(
            Q(updated_at__lt=cutoff)
            | Q(updated_at__isnull=True, started_at__lt=cutoff)
            | Q(updated_at__isnull=True, started_at__isnull=True, create_time__lt=cutoff)
        )
        .values_list("id", flat=True)
    )
    if not ids:
        return 0
    return _reclaim_export_ids(
        ids,
        reason=f"进度超时（>{stale_seconds}s），已自动重新排队",
    )


def _reclaim_export_ids(ids: list[int], *, reason: str) -> int:
    now = timezone.now()
    jobs = list(
        BlobSimulatedExportJob.objects.filter(pk__in=ids).only("id", "rows_written", "last_offset")
    )
    for job in jobs:
        offset = int(getattr(job, "last_offset", 0) or 0)
        written = int(job.rows_written or 0)
        BlobSimulatedExportJob.objects.filter(pk=job.pk).update(
            status=BlobSimulatedExportJob.STATUS_PENDING,
            pause_requested=0,
            cancel_requested=0,
            message=f"{reason}（已写 {written} 行，offset={offset}）"[:500],
            updated_at=now,
        )
    return len(jobs)


def _update_job(job_id: int, **fields) -> None:
    fields["updated_at"] = timezone.now()
    BlobSimulatedExportJob.objects.filter(pk=job_id).update(**fields)


def _export_queue_held(*, exclude_id: int | None = None) -> bool:
    """Running or paused jobs occupy the serial queue slot (pause does not advance)."""
    qs = BlobSimulatedExportJob.objects.filter(
        status__in={
            BlobSimulatedExportJob.STATUS_RUNNING,
            BlobSimulatedExportJob.STATUS_PAUSED,
        }
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return qs.exists()


def execute_export_job(job_id: int, *, kick_next: bool = True) -> None:
    close_old_connections()
    advance_queue = True
    try:
        with transaction.atomic():
            job = (
                BlobSimulatedExportJob.objects.select_for_update()
                .filter(pk=job_id, status=BlobSimulatedExportJob.STATUS_PENDING)
                .first()
            )
            if not job:
                return
            if _export_queue_held(exclude_id=job_id):
                # Slot held by another running/paused job — leave pending; do not kick-storm.
                advance_queue = False
                return
            if job.cancel_requested:
                _update_job(
                    job_id,
                    status=BlobSimulatedExportJob.STATUS_CANCELLED,
                    finished_at=timezone.now(),
                    message="已取消",
                )
                return
            now = timezone.now()
            BlobSimulatedExportJob.objects.filter(pk=job_id).update(
                status=BlobSimulatedExportJob.STATUS_RUNNING,
                started_at=job.started_at or now,
                pause_requested=0,
                message="正在导出…",
                updated_at=now,
            )

        job = BlobSimulatedExportJob.objects.filter(pk=job_id).first()
        if not job or job.status != BlobSimulatedExportJob.STATUS_RUNNING:
            return

        start_offset = int(getattr(job, "last_offset", 0) or 0)
        resume = start_offset > 0

        def progress_callback(
            *,
            rows_written: int,
            total_estimate: int | None = None,
            offset: int | None = None,
        ) -> None:
            fields: dict[str, Any] = {
                "rows_written": int(rows_written or 0),
                "message": f"已写入 {int(rows_written or 0)} 行…",
            }
            if offset is not None:
                fields["last_offset"] = int(offset)
            if total_estimate is not None and int(total_estimate) >= 0:
                fields["total_estimate"] = int(total_estimate)
            refreshed = (
                BlobSimulatedExportJob.objects.filter(pk=job_id)
                .only("cancel_requested", "pause_requested")
                .first()
            )
            if refreshed and refreshed.cancel_requested:
                raise SimulatedExportCancelled("用户取消导出")
            if refreshed and refreshed.pause_requested:
                raise SimulatedExportPaused(
                    "用户暂停导出",
                    offset=int(offset if offset is not None else start_offset),
                    rows_written=int(rows_written or 0),
                )
            _update_job(job_id, **fields)

        def should_cancel() -> bool:
            refreshed = (
                BlobSimulatedExportJob.objects.filter(pk=job_id).only("cancel_requested").first()
            )
            return bool(refreshed and refreshed.cancel_requested)

        def should_pause() -> bool:
            refreshed = (
                BlobSimulatedExportJob.objects.filter(pk=job_id).only("pause_requested").first()
            )
            return bool(refreshed and refreshed.pause_requested)

        try:
            result = export_simulated_table_to_connection(
                job.view_id,
                target_connection_id=job.target_connection_id,
                target_db_alias=job.target_db_alias or None,
                target_database=job.target_database or "",
                target_table=job.target_table or "",
                if_exists=job.if_exists or "fail",
                start_offset=start_offset,
                skip_prepare=resume,
                progress_callback=progress_callback,
                should_cancel=should_cancel,
                should_pause=should_pause,
            )
        except SimulatedExportPaused as exc:
            advance_queue = False
            _update_job(
                job_id,
                status=BlobSimulatedExportJob.STATUS_PAUSED,
                pause_requested=0,
                last_offset=int(exc.offset or 0),
                rows_written=int(exc.rows_written or 0),
                message=f"已暂停（已写 {int(exc.rows_written or 0)} 行）"[:500],
                last_error="",
            )
            return
        except SimulatedExportCancelled as exc:
            _update_job(
                job_id,
                status=BlobSimulatedExportJob.STATUS_CANCELLED,
                finished_at=timezone.now(),
                message=str(exc)[:500] or "已取消",
                last_error="",
            )
            return
        except (SimulatedExportError, Exception) as exc:
            logger.exception("simulated export job failed job_id=%s", job_id)
            _update_job(
                job_id,
                status=BlobSimulatedExportJob.STATUS_FAILED,
                finished_at=timezone.now(),
                message=f"导出失败: {exc}"[:500],
                last_error=str(exc)[:500],
            )
            return

        rows = int(result.get("rows_written") or 0)
        msg = (
            f"导出完成：{rows} 行 → "
            f"{result.get('target_database')}.{result.get('target_table')}"
        )
        if result.get("target_view_error"):
            msg += f"；浏览配置警告：{result['target_view_error']}"
        _update_job(
            job_id,
            status=BlobSimulatedExportJob.STATUS_COMPLETED,
            rows_written=rows,
            last_offset=int(result.get("last_offset") or rows),
            total_estimate=max(int(job.total_estimate or 0), rows),
            finished_at=timezone.now(),
            message=msg[:500],
            result_json=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        )
    finally:
        close_old_connections()
        connection.close()
        # Advance only on terminal outcomes (complete / fail / cancel), not pause.
        if advance_queue and kick_next:
            try:
                kick_export_queue()
            except Exception:
                logger.warning("kick export queue after job failed", exc_info=True)


def _run_export_worker(job_id: int) -> None:
    try:
        execute_export_job(job_id)
    except Exception:
        logger.exception("export worker crashed job_id=%s", job_id)


def kick_export_job_async(job_id: int) -> None:
    # sqlite tests cannot share write locks across threads reliably.
    if connection.vendor == "sqlite" or getattr(settings, "BLOB_EXPORT_SYNC", False):
        logger.info("running simulated export synchronously job_id=%s", job_id)
        execute_export_job(job_id)
        return
    thread = threading.Thread(
        target=_run_export_worker,
        args=(job_id,),
        name=f"blob-export-{job_id}",
        daemon=True,
    )
    thread.start()
    logger.info("kicked simulated export thread job_id=%s", job_id)


def kick_export_queue(*, reclaim_stale: bool = True) -> int | None:
    """Start the oldest pending export in a worker thread if the queue slot is free.

    Paused/running jobs hold the slot (pause does not auto-start the next job).
    Always spawns work here — leaving jobs pending for a sidecar alone caused
    permanent「排队中」when the sidecar/scheduler path failed to run.
    """
    if reclaim_stale:
        try:
            reclaim_stale_running_export_jobs(stale_seconds=300)
        except Exception:
            logger.warning("reclaim stale exports before kick failed", exc_info=True)
    if _export_queue_held():
        holders = list(
            BlobSimulatedExportJob.objects.filter(
                status__in={
                    BlobSimulatedExportJob.STATUS_RUNNING,
                    BlobSimulatedExportJob.STATUS_PAUSED,
                }
            ).values_list("id", "status")[:5]
        )
        logger.info("kick_export_queue skipped; held by %s", holders)
        return None
    next_id = (
        BlobSimulatedExportJob.objects.filter(status=BlobSimulatedExportJob.STATUS_PENDING)
        .order_by("id")
        .values_list("id", flat=True)
        .first()
    )
    if not next_id:
        return None
    kick_export_job_async(int(next_id))
    return int(next_id)


def process_pending_export_jobs(
    *,
    max_jobs: int = 1,
    stale_seconds: int = 300,
) -> int:
    """Run pending exports synchronously (scheduler / sidecar). Returns count executed."""
    try:
        from images.schema_ensure import ensure_blob_export_job_schema

        ensure_blob_export_job_schema()
    except Exception:
        logger.warning("ensure export schema before process failed", exc_info=True)
    try:
        reclaim_stale_running_export_jobs(stale_seconds=stale_seconds)
    except Exception:
        logger.warning("reclaim exports before process failed", exc_info=True)

    started = 0
    for _ in range(max(1, max_jobs)):
        # RUNNING or PAUSED hold the slot (pause must not auto-start the next job).
        if _export_queue_held():
            holders = list(
                BlobSimulatedExportJob.objects.filter(
                    status__in={
                        BlobSimulatedExportJob.STATUS_RUNNING,
                        BlobSimulatedExportJob.STATUS_PAUSED,
                    }
                ).values_list("id", "status")[:5]
            )
            logger.info("export queue held by %s — skip pending", holders)
            break
        next_id = (
            BlobSimulatedExportJob.objects.filter(status=BlobSimulatedExportJob.STATUS_PENDING)
            .order_by("id")
            .values_list("id", flat=True)
            .first()
        )
        if not next_id:
            break
        logger.info("process_pending_export starting job_id=%s", next_id)
        execute_export_job(int(next_id), kick_next=False)
        started += 1
    return started
