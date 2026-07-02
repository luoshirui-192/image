"""Logical delete retention schedule helpers."""
from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone


def get_retention_days() -> int:
    return int(getattr(settings, "DELETED_IMAGE_RETENTION_DAYS", 30))


def build_deletion_info(deleted_at: datetime | None) -> dict:
    """
    Compute when a logically deleted image will be physically removed.

    Physical cleanup runs when update_time <= now - retention_days,
    i.e. purge_at = deleted_at + retention_days.
    """
    retention_days = get_retention_days()
    if deleted_at is None:
        deleted_at = timezone.now()

    if timezone.is_naive(deleted_at):
        deleted_at = timezone.make_aware(deleted_at, timezone.get_current_timezone())

    purge_at = deleted_at + timedelta(days=retention_days)
    now = timezone.now()
    seconds_left = max(0, int((purge_at - now).total_seconds()))
    days_remaining = seconds_left // 86400
    hours_remaining = (seconds_left % 86400) // 3600

    return {
        "retention_days": retention_days,
        "deleted_at": deleted_at.isoformat(sep=" ", timespec="seconds"),
        "purge_at": purge_at.isoformat(sep=" ", timespec="seconds"),
        "days_remaining": days_remaining,
        "hours_remaining": hours_remaining,
        "seconds_remaining": seconds_left,
        "expired": seconds_left == 0,
    }


def format_deletion_notice(deletion_info: dict) -> str:
    """Human-readable retention summary for UI dialogs."""
    retention_days = deletion_info["retention_days"]
    if deletion_info["expired"]:
        return f"该图片已超过保留期（{retention_days} 天），可能随时被系统清理。"

    days = deletion_info["days_remaining"]
    hours = deletion_info["hours_remaining"]
    purge_at = deletion_info["purge_at"]

    if days > 0:
        remaining = f"约 {days} 天"
        if hours > 0:
            remaining += f" {hours} 小时"
    elif hours > 0:
        remaining = f"约 {hours} 小时"
    else:
        remaining = "不足 1 小时"

    return (
        f"删除后文件仍保留 {retention_days} 天，预计 {purge_at} 永久删除（剩余 {remaining}）。"
        f"在此之前可在「含已删」列表中恢复。"
    )
