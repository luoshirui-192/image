"""Background fingerprint zip import jobs (daemon thread, like blob migration)."""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import BinaryIO

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from fingerprints.models import FingerprintImportJob
from fingerprints.services import FingerprintImportError, discover_pair_dirs, import_pair_directory
from utils.db_time import fetch_db_now

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = frozenset(
    {FingerprintImportJob.STATUS_PENDING, FingerprintImportJob.STATUS_RUNNING}
)


def _import_workers() -> int:
    if connection.vendor == "sqlite":
        return 1
    return max(1, min(8, int(getattr(settings, "FP_IMPORT_WORKERS", 4) or 4)))


def serialize_import_job(job: FingerprintImportJob) -> dict:
    total = int(job.total_estimate or 0)
    done = int(job.processed or 0)
    if job.status == FingerprintImportJob.STATUS_COMPLETED:
        percent = 100.0
    elif total > 0:
        percent = min(99.0, round(100.0 * done / total, 2))
    else:
        percent = 0.0
    return {
        "id": job.id,
        "zip_name": job.zip_name,
        "status": job.status,
        "algo_version": job.algo_version,
        "skip_existing": bool(job.skip_existing),
        "total_estimate": total,
        "processed": done,
        "succeeded": int(job.succeeded or 0),
        "failed": int(job.failed or 0),
        "skipped": int(job.skipped or 0),
        "percent": percent,
        "cancel_requested": bool(job.cancel_requested),
        "message": job.message,
        "last_error": job.last_error,
        "created_by": job.created_by,
        "create_time": job.create_time.isoformat(sep=" ") if job.create_time else None,
        "started_at": job.started_at.isoformat(sep=" ") if job.started_at else None,
        "finished_at": job.finished_at.isoformat(sep=" ") if job.finished_at else None,
        "updated_at": job.updated_at.isoformat(sep=" ") if job.updated_at else None,
    }


def _staging_dir() -> Path:
    root = Path(tempfile.gettempdir()) / "image_db_fp_import"
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_upload_to_staging(upload: BinaryIO, *, filename: str) -> Path:
    """Stream uploaded zip to disk (avoid holding whole archive in RAM)."""
    safe_name = Path(filename or "upload.zip").name
    target = _staging_dir() / f"upload_{os.getpid()}_{threading.get_ident()}_{safe_name}"
    with open(target, "wb") as out:
        if hasattr(upload, "chunks"):
            for chunk in upload.chunks():
                out.write(chunk)
        else:
            shutil.copyfileobj(upload, out)
    return target


def create_import_job(
    *,
    zip_path: str,
    zip_name: str,
    created_by: str,
    algo_version: str = "1.0",
    tags: str = "fingerprint",
    skip_existing: bool = True,
    category_id: int | None = None,
) -> FingerprintImportJob:
    now = fetch_db_now()
    job = FingerprintImportJob(
        zip_path=zip_path,
        zip_name=zip_name[:255],
        status=FingerprintImportJob.STATUS_PENDING,
        algo_version=(algo_version or "1.0")[:64],
        tags=(tags or "fingerprint")[:500],
        skip_existing=1 if skip_existing else 0,
        category_id=category_id,
        created_by=(created_by or "")[:100],
        message="排队中…",
        create_time=now,
        updated_at=now,
    )
    job.save()
    return job


def cancel_import_job(job_id: int) -> FingerprintImportJob:
    job = FingerprintImportJob.objects.filter(id=job_id).first()
    if not job:
        raise FingerprintImportError("导入任务不存在")
    if job.status in {
        FingerprintImportJob.STATUS_COMPLETED,
        FingerprintImportJob.STATUS_FAILED,
        FingerprintImportJob.STATUS_CANCELLED,
    }:
        return job
    now = timezone.now()
    FingerprintImportJob.objects.filter(pk=job.pk).update(
        cancel_requested=1,
        updated_at=now,
        message="正在取消…",
    )
    if job.status == FingerprintImportJob.STATUS_PENDING:
        FingerprintImportJob.objects.filter(pk=job.pk).update(
            status=FingerprintImportJob.STATUS_CANCELLED,
            finished_at=now,
            message="已取消",
        )
    return FingerprintImportJob.objects.get(pk=job.pk)


def _update_progress(job_id: int, **fields) -> None:
    fields["updated_at"] = timezone.now()
    FingerprintImportJob.objects.filter(pk=job_id).update(**fields)


def _import_one_pair(pair_dir: Path, job: FingerprintImportJob) -> tuple[str, str]:
    """Return (outcome, detail) where outcome in succeeded|skipped|failed."""
    close_old_connections()
    try:
        result = import_pair_directory(
            pair_dir,
            upload_user=job.created_by or "import",
            tags=job.tags,
            algo_version=job.algo_version,
            category_id=job.category_id,
            skip_existing=bool(job.skip_existing),
        )
        if result.skipped:
            return "skipped", result.batch_name
        return "succeeded", result.batch_name
    except Exception as exc:
        logger.warning("fingerprint pair import failed dir=%s: %s", pair_dir, exc)
        return "failed", f"{pair_dir.name}: {exc}"[:480]
    finally:
        close_old_connections()


def _claim_job(job_id: int) -> FingerprintImportJob | None:
    """Mark pending → running. Avoid select_for_update on sqlite (test DB locks)."""
    now = timezone.now()
    if connection.vendor == "sqlite":
        updated = FingerprintImportJob.objects.filter(
            pk=job_id,
            status=FingerprintImportJob.STATUS_PENDING,
        ).update(
            status=FingerprintImportJob.STATUS_RUNNING,
            started_at=now,
            updated_at=now,
            message="解压并扫描配对目录…",
        )
        if not updated:
            return None
        return FingerprintImportJob.objects.get(pk=job_id)

    with transaction.atomic():
        job = (
            FingerprintImportJob.objects.select_for_update()
            .filter(pk=job_id, status=FingerprintImportJob.STATUS_PENDING)
            .first()
        )
        if not job:
            return None
        FingerprintImportJob.objects.filter(pk=job_id).update(
            status=FingerprintImportJob.STATUS_RUNNING,
            started_at=now,
            updated_at=now,
            message="解压并扫描配对目录…",
        )
    return FingerprintImportJob.objects.get(pk=job_id)


def execute_import_job(job_id: int) -> None:
    close_old_connections()
    try:
        job = _claim_job(job_id)
        if not job:
            return
        zip_path = Path(job.zip_path)
        if not zip_path.is_file():
            raise FingerprintImportError(f"zip 文件不存在: {job.zip_path}")

        work_dir = Path(tempfile.mkdtemp(prefix=f"fp_job_{job_id}_", dir=str(_staging_dir())))
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(work_dir)
            pair_dirs = discover_pair_dirs(work_dir)
            if not pair_dirs:
                raise FingerprintImportError("压缩包中未找到 batmatch 风格的成对目录")

            _update_progress(
                job_id,
                total_estimate=len(pair_dirs),
                message=f"发现 {len(pair_dirs)} 对，开始导入…",
            )

            succeeded = skipped = failed = processed = 0
            workers = _import_workers()
            last_error = ""

            def _handle_outcome(outcome: str, detail: str) -> bool:
                """Apply one pair result; return False if cancelled."""
                nonlocal succeeded, skipped, failed, processed, last_error
                refreshed = FingerprintImportJob.objects.filter(pk=job_id).only(
                    "cancel_requested"
                ).first()
                if refreshed and refreshed.cancel_requested:
                    _update_progress(
                        job_id,
                        status=FingerprintImportJob.STATUS_CANCELLED,
                        processed=processed,
                        succeeded=succeeded,
                        failed=failed,
                        skipped=skipped,
                        finished_at=timezone.now(),
                        message=f"已取消（成功 {succeeded} · 跳过 {skipped} · 失败 {failed}）",
                    )
                    return False

                processed += 1
                if outcome == "succeeded":
                    succeeded += 1
                elif outcome == "skipped":
                    skipped += 1
                else:
                    failed += 1
                    last_error = detail

                if processed % 2 == 0 or processed == len(pair_dirs):
                    _update_progress(
                        job_id,
                        processed=processed,
                        succeeded=succeeded,
                        failed=failed,
                        skipped=skipped,
                        last_error=last_error[:500],
                        message=(
                            f"导入中 {processed}/{len(pair_dirs)}："
                            f"成功 {succeeded} · 跳过 {skipped} · 失败 {failed}"
                        ),
                    )
                return True

            if workers <= 1:
                for pair_dir in pair_dirs:
                    outcome, detail = _import_one_pair(pair_dir, job)
                    if not _handle_outcome(outcome, detail):
                        return
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {pool.submit(_import_one_pair, d, job): d for d in pair_dirs}
                    for fut in as_completed(futures):
                        outcome, detail = fut.result()
                        if not _handle_outcome(outcome, detail):
                            for pending in futures:
                                pending.cancel()
                            return

            status = FingerprintImportJob.STATUS_COMPLETED
            if succeeded == 0 and failed > 0:
                status = FingerprintImportJob.STATUS_FAILED
            _update_progress(
                job_id,
                status=status,
                processed=processed,
                succeeded=succeeded,
                failed=failed,
                skipped=skipped,
                last_error=last_error[:500],
                finished_at=timezone.now(),
                message=(
                    f"导入完成（成功 {succeeded} · 跳过 {skipped} · 失败 {failed}）"
                ),
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            try:
                zip_path.unlink(missing_ok=True)
            except OSError:
                pass
    except Exception as exc:
        logger.exception("fingerprint import job failed job_id=%s", job_id)
        _update_progress(
            job_id,
            status=FingerprintImportJob.STATUS_FAILED,
            finished_at=timezone.now(),
            message=f"导入失败: {exc}"[:500],
            last_error=str(exc)[:500],
        )
    finally:
        close_old_connections()
        connection.close()


def _run_import_worker(job_id: int) -> None:
    try:
        execute_import_job(job_id)
    except Exception:
        logger.exception("fingerprint import worker crashed job_id=%s", job_id)


def kick_import_job_async(job_id: int) -> None:
    # sqlite (unit tests) cannot share write locks across threads reliably.
    if connection.vendor == "sqlite" or getattr(settings, "FP_IMPORT_SYNC", False):
        logger.info("running fingerprint import synchronously job_id=%s", job_id)
        execute_import_job(job_id)
        return
    thread = threading.Thread(
        target=_run_import_worker,
        args=(job_id,),
        name=f"fp-import-{job_id}",
        daemon=True,
    )
    thread.start()
    logger.info("kicked fingerprint import thread job_id=%s", job_id)
