"""Physically remove an image: disk files, source maps, and image_info row."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

from images.file_service import thumb_cache_path
from images.models import ImageInfo, ImageSourceMap
from utils.file_security import PathSecurityError, resolve_safe_upload_file

logger = logging.getLogger(__name__)


class PurgeError(Exception):
    pass


@dataclass
class PurgeResult:
    image_id: int
    image_name: str
    image_path: str
    file_deleted: bool = False
    thumb_deleted: bool = False
    source_maps_deleted: int = 0


def _delete_upload_file(relative_path: str) -> tuple[bool, int]:
    if not relative_path:
        return False, 0
    try:
        abs_path = resolve_safe_upload_file(settings.UPLOAD_ROOT, relative_path)
        if not abs_path.is_file():
            return False, 0
        size = abs_path.stat().st_size
        abs_path.unlink()
        return True, size
    except PathSecurityError as exc:
        logger.warning("skip unsafe path during purge path=%s: %s", relative_path, exc)
        return False, 0
    except OSError:
        logger.warning("failed to delete file during purge path=%s", relative_path, exc_info=True)
        return False, 0


def _delete_thumb(relative_path: str) -> bool:
    if not relative_path:
        return False
    try:
        cache_path = thumb_cache_path(relative_path)
        if cache_path.is_file():
            cache_path.unlink()
            return True
    except (PathSecurityError, OSError):
        logger.warning("failed to delete thumb during purge path=%s", relative_path, exc_info=True)
    return False


def purge_image_record(image: ImageInfo) -> PurgeResult:
    """Delete upload file, thumb cache, source maps, then the image_info row."""
    image_id = image.id
    image_name = image.image_name
    image_path = image.image_path

    file_deleted, _ = _delete_upload_file(image_path)
    thumb_deleted = _delete_thumb(image_path)
    maps_deleted, _ = ImageSourceMap.objects.filter(image_info_id=image_id).delete()

    image.delete()

    return PurgeResult(
        image_id=image_id,
        image_name=image_name,
        image_path=image_path,
        file_deleted=file_deleted,
        thumb_deleted=thumb_deleted,
        source_maps_deleted=maps_deleted,
    )
