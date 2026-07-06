"""Restore logically deleted images."""
from __future__ import annotations

from images.models import ImageInfo
from images.services import find_duplicate_image
from utils.storage import get_image_storage


class RestoreError(Exception):
    """Raised when an image cannot be restored."""


def _get_deleted_image(pk: int) -> ImageInfo:
    try:
        image = ImageInfo.objects.get(pk=pk, is_delete=1)
    except ImageInfo.DoesNotExist as exc:
        raise RestoreError("图片不存在或未处于已删除状态") from exc
    return image


def _assert_can_restore(user, image: ImageInfo) -> None:
    if getattr(user, "role", "") == "admin":
        return
    if image.upload_user != getattr(user, "username", ""):
        raise RestoreError("只能恢复自己上传的图片")


def _assert_file_exists(relative_path: str) -> None:
    if not relative_path:
        raise RestoreError("图片路径无效，无法恢复")
    if not get_image_storage().exists(relative_path):
        raise RestoreError("磁盘文件已不存在，无法恢复（可能已超过保留期被清理）")


def _assert_no_active_duplicate(image: ImageInfo) -> None:
    conflict = find_duplicate_image(filename=image.image_name, content_hash=image.file_hash or "")
    if conflict and conflict.id != image.id:
        raise RestoreError(f"已有同名或相同内容的图片（ID={conflict.id}），请先处理冲突后再恢复")


def restore_image(*, pk: int, user) -> ImageInfo:
    """Set is_delete=0 after validation."""
    image = _get_deleted_image(pk)
    _assert_can_restore(user, image)
    _assert_file_exists(image.image_path)
    _assert_no_active_duplicate(image)

    image.is_delete = 0
    image.save(update_fields=["is_delete"])
    return image
