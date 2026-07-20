"""Background jobs for simulated table export (avoid gateway 504 on long sync POST)."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from django.conf import settings
from django.db import close_old_connections, connection
from django.utils import timezone

from images.blob_simulated_export_service import (
    SimulatedExportCancelled,
    SimulatedExportError,
    export_simulated_table_to_connection,
)
from images.models import BlobSimulatedExportJob
from utils.db_time import fetch_db_now

logger = logging.getLogger(__name__)


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
        "percent": percent,
        "cancel_requested": bool(job.cancel_requested),
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
        updated_at=now,
        message="正在取消…",
    )
    if job.status == BlobSimulatedExportJob.STATUS_PENDING:
        BlobSimulatedExportJob.objects.filter(pk=job.pk).update(
            status=BlobSimulatedExportJob.STATUS_CANCELLED,
            finished_at=now,
            message="已取消",
        )
    return BlobSimulatedExportJob.objects.get(pk=job.pk)


def _update_job(job_id: int, **fields) -> None:
    fields["updated_at"] = timezone.now()
    BlobSimulatedExportJob.objects.filter(pk=job_id).update(**fields)


def execute_export_job(job_id: int) -> None:
    close_old_connections()
    try:
        job = BlobSimulatedExportJob.objects.filter(pk=job_id).first()
        if not job:
            return
        if job.status != BlobSimulatedExportJob.STATUS_PENDING:
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
        _update_job(
            job_id,
            status=BlobSimulatedExportJob.STATUS_RUNNING,
            started_at=now,
            message="正在导出…",
        )

        def progress_callback(*, rows_written: int, total_estimate: int | None = None) -> None:
            fields: dict[str, Any] = {
                "rows_written": int(rows_written or 0),
                "message": f"已写入 {int(rows_written or 0)} 行…",
            }
            if total_estimate is not None and int(total_estimate) >= 0:
                fields["total_estimate"] = int(total_estimate)
            refreshed = BlobSimulatedExportJob.objects.filter(pk=job_id).only("cancel_requested").first()
            if refreshed and refreshed.cancel_requested:
                raise SimulatedExportCancelled("用户取消导出")
            _update_job(job_id, **fields)

        def should_cancel() -> bool:
            refreshed = BlobSimulatedExportJob.objects.filter(pk=job_id).only("cancel_requested").first()
            return bool(refreshed and refreshed.cancel_requested)

        try:
            result = export_simulated_table_to_connection(
                job.view_id,
                target_connection_id=job.target_connection_id,
                target_db_alias=job.target_db_alias or None,
                target_database=job.target_database or "",
                target_table=job.target_table or "",
                if_exists=job.if_exists or "fail",
                progress_callback=progress_callback,
                should_cancel=should_cancel,
            )
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
            total_estimate=max(int(job.total_estimate or 0), rows),
            finished_at=timezone.now(),
            message=msg[:500],
            result_json=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        )
    finally:
        close_old_connections()
        connection.close()


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
