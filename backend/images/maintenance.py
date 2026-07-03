"""Scheduled maintenance: deleted file cleanup and storage stats — Step 16."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from images.models import ImageCategory, ImageInfo
from images.purge_service import purge_image_record
from logs.models import OperateLog
from utils.file_security import PathSecurityError, resolve_safe_upload_file

logger = logging.getLogger(__name__)


@dataclass
class CleanupResult:
    scanned: int = 0
    files_deleted: int = 0
    thumbs_deleted: int = 0
    bytes_freed: int = 0
    errors: list[str] = field(default_factory=list)


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def cleanup_deleted_image_files(
    *,
    retention_days: int | None = None,
    dry_run: bool = False,
) -> CleanupResult:
    """
    Permanently purge logically deleted images (legacy is_delete=1) past retention.

    Web delete now purges immediately; this cleans historical soft-deleted rows.
    """
    days = retention_days if retention_days is not None else settings.DELETED_IMAGE_RETENTION_DAYS
    cutoff = timezone.now() - timedelta(days=days)
    result = CleanupResult()

    queryset = ImageInfo.objects.filter(is_delete=1, update_time__lte=cutoff).order_by("id")
    result.scanned = queryset.count()

    for image in list(queryset.iterator()):
        if dry_run:
            relative_path = image.image_path or ""
            if relative_path:
                try:
                    abs_path = resolve_safe_upload_file(settings.UPLOAD_ROOT, relative_path)
                    if abs_path.is_file():
                        result.files_deleted += 1
                        result.bytes_freed += abs_path.stat().st_size
                except (PathSecurityError, OSError) as exc:
                    result.errors.append(f"id={image.id}: {exc}")
            continue

        try:
            purge_result = purge_image_record(image)
            if purge_result.file_deleted:
                result.files_deleted += 1
            if purge_result.thumb_deleted:
                result.thumbs_deleted += 1
        except Exception as exc:
            result.errors.append(f"id={image.id}: {exc}")
            logger.warning("failed to purge legacy deleted image id=%s", image.id, exc_info=True)

    return result


def purge_old_operate_logs(
    *,
    retention_days: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Delete operate_log rows older than retention period."""
    days = retention_days if retention_days is not None else settings.LOG_RETENTION_DAYS
    cutoff = timezone.now() - timedelta(days=days)
    queryset = OperateLog.objects.filter(create_time__lt=cutoff)
    count = queryset.count()
    if not dry_run and count:
        queryset.delete()
    return {"retention_days": days, "deleted": count, "dry_run": dry_run}


def compute_storage_stats() -> dict:
    """Aggregate image counts and disk usage for admin dashboard."""
    active_qs = ImageInfo.objects.filter(is_delete=0)
    deleted_count = ImageInfo.objects.filter(is_delete=1).count()

    category_rows = (
        active_qs.values("category_id")
        .annotate(count=Count("id"), total_bytes=Sum("file_size"))
        .order_by("-count")
    )
    category_map = {c.id: c.category_name for c in ImageCategory.objects.all()}

    by_category = []
    for row in category_rows:
        cid = row["category_id"]
        by_category.append(
            {
                "category_id": cid,
                "category_name": category_map.get(cid, "未分类" if not cid else str(cid)),
                "count": row["count"] or 0,
                "total_bytes": row["total_bytes"] or 0,
            }
        )

    upload_root = Path(settings.UPLOAD_ROOT)
    if upload_root.name != "upload" and (upload_root / "upload").is_dir():
        upload_dir = upload_root / "upload"
    else:
        upload_dir = upload_root

    return {
        "image_active_count": active_qs.count(),
        "image_deleted_count": deleted_count,
        "image_total_bytes": active_qs.aggregate(total=Sum("file_size"))["total"] or 0,
        "upload_disk_bytes": _dir_size(upload_dir),
        "thumb_cache_bytes": _dir_size(Path(settings.THUMB_CACHE_ROOT)),
        "by_category": by_category,
        "generated_at": timezone.now().isoformat(sep=" ", timespec="seconds"),
    }
