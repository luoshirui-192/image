"""Batch logical delete for images."""
from __future__ import annotations

from dataclasses import dataclass, field

from images.deletion_policy import build_deletion_info, format_deletion_notice, get_retention_days
from images.models import ImageInfo


@dataclass
class BatchDeleteItemResult:
    id: int
    success: bool
    image_name: str = ""
    error: str = ""
    deletion_info: dict | None = None


@dataclass
class BatchDeleteResult:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    retention_days: int = 0
    notice: str = ""
    items: list[BatchDeleteItemResult] = field(default_factory=list)


def _logical_delete_record(image: ImageInfo) -> dict:
    image.is_delete = 1
    image.save(update_fields=["is_delete"])
    image.refresh_from_db()
    deletion_info = build_deletion_info(image.update_time)
    return {
        "image_name": image.image_name,
        "deletion_info": deletion_info,
        "notice": format_deletion_notice(deletion_info),
    }


def batch_logical_delete(ids: list[int]) -> BatchDeleteResult:
    """Logically delete multiple active images by id."""
    retention_days = get_retention_days()
    unique_ids: list[int] = []
    seen: set[int] = set()
    for raw_id in ids:
        if raw_id not in seen:
            seen.add(raw_id)
            unique_ids.append(raw_id)

    result = BatchDeleteResult(
        total=len(unique_ids),
        retention_days=retention_days,
        notice=(
            f"逻辑删除后文件保留 {retention_days} 天，到期自动永久删除；"
            f"保留期内可在「含已删」列表中恢复。"
        ),
    )

    for image_id in unique_ids:
        image = ImageInfo.objects.filter(pk=image_id, is_delete=0).first()
        if image is None:
            result.items.append(
                BatchDeleteItemResult(
                    id=image_id,
                    success=False,
                    error="图片不存在或已删除",
                )
            )
            result.failed += 1
            continue

        payload = _logical_delete_record(image)
        result.items.append(
            BatchDeleteItemResult(
                id=image_id,
                success=True,
                image_name=payload["image_name"],
                deletion_info=payload["deletion_info"],
            )
        )
        result.succeeded += 1

    return result


def serialize_batch_delete_result(result: BatchDeleteResult) -> dict:
    return {
        "summary": {
            "total": result.total,
            "succeeded": result.succeeded,
            "failed": result.failed,
            "retention_days": result.retention_days,
        },
        "notice": result.notice,
        "items": [
            {
                "id": item.id,
                "success": item.success,
                "image_name": item.image_name,
                "error": item.error,
                "deletion_info": item.deletion_info,
            }
            for item in result.items
        ],
    }
