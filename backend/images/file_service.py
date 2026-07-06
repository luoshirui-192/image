"""Image file read, thumbnail, and download — Step 14."""
from __future__ import annotations

import hashlib
import logging
from io import BytesIO
from pathlib import Path

from django.conf import settings
from PIL import Image

from images.models import ImageInfo
from utils.file_security import (
    AccessDeniedError,
    PathSecurityError,
    assert_safe_relative_path,
    check_image_access_allowed,
    create_image_access_token,
    guess_mime,
)
from utils.path_builder import normalize_suffix
from utils.storage import get_image_storage

logger = logging.getLogger(__name__)


class ImageNotFoundError(Exception):
    """Raised when DB record or disk file is missing."""


class ImageResolveError(Exception):
    """Raised when path/id parameters are invalid."""


def lookup_image_record(*, path: str | None = None, image_id: int | None = None) -> ImageInfo | None:
    if image_id is not None:
        try:
            return ImageInfo.objects.get(pk=image_id, is_delete=0)
        except ImageInfo.DoesNotExist:
            return None
    if path:
        return ImageInfo.objects.filter(image_path=path, is_delete=0).first()
    return None


def resolve_image_location(
    *,
    path: str | None = None,
    image_id: int | None = None,
) -> tuple[str, str]:
    """
    Resolve relative path and download filename from query params.

    Returns:
        (relative_path, download_filename)
    """
    if image_id is None and not path:
        raise ImageResolveError("请提供 path 或 id 参数")

    record = lookup_image_record(path=path, image_id=image_id)
    if record is not None:
        return record.image_path, record.image_name or Path(record.image_path).name

    if image_id is not None:
        raise ImageNotFoundError("图片记录不存在")

    if not path:
        raise ImageResolveError("请提供 path 或 id 参数")

    safe_path = assert_safe_relative_path(path)
    return safe_path, Path(safe_path).name


def ensure_access_allowed(
    relative_path: str,
    *,
    is_authenticated: bool,
    access_token: str | None,
) -> None:
    check_image_access_allowed(
        relative_path,
        is_authenticated=is_authenticated,
        access_token=access_token,
        secret=settings.IMAGE_ACCESS_SECRET,
    )


def image_exists(relative_path: str) -> bool:
    return get_image_storage().exists(relative_path)


def get_absolute_image_path(relative_path: str) -> Path:
    """Return local path for FileResponse (local backend only)."""
    storage = get_image_storage()
    if storage.backend_name != "local":
        raise ImageNotFoundError("当前存储后端不支持本地路径访问")
    try:
        return storage.get_local_path(relative_path)
    except FileNotFoundError as exc:
        raise ImageNotFoundError("图片文件不存在") from exc


def read_image_bytes(relative_path: str) -> bytes:
    storage = get_image_storage()
    try:
        return storage.read_bytes(relative_path)
    except FileNotFoundError as exc:
        raise ImageNotFoundError("图片文件不存在") from exc


def thumb_cache_path(relative_path: str) -> Path:
    """Cache file path keyed by image path + thumbnail size."""
    max_size = getattr(settings, "THUMB_SIZE", 200)
    digest = hashlib.sha256(f"{relative_path}:{max_size}".encode("utf-8")).hexdigest()
    cache_root = Path(settings.THUMB_CACHE_ROOT)
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root / f"{digest}.jpg"


def _write_thumbnail_atomically(cache_file: Path, image: Image.Image) -> None:
    """Write JPEG to a temp file then replace to avoid partial cache reads."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_file.with_suffix(".jpg.tmp")
    try:
        image.save(temp_path, format="JPEG", quality=85, optimize=True)
        temp_path.replace(cache_file)
    finally:
        if temp_path.is_file():
            temp_path.unlink(missing_ok=True)


def get_or_create_thumbnail(relative_path: str) -> Path:
    """Generate cached thumbnail on first access; return cache file path."""
    storage = get_image_storage()
    src_stat = storage.stat(relative_path)
    if src_stat is None:
        raise ImageNotFoundError("图片文件不存在")

    cache_file = thumb_cache_path(relative_path)
    if cache_file.is_file() and cache_file.stat().st_mtime >= src_stat.mtime:
        return cache_file

    max_size = settings.THUMB_SIZE
    try:
        content = storage.read_bytes(relative_path)
        with Image.open(BytesIO(content)) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            _write_thumbnail_atomically(cache_file, img)
    except ImageNotFoundError:
        raise
    except Exception as exc:
        logger.exception("thumbnail generation failed for %s", relative_path)
        raise ImageNotFoundError("无法生成缩略图") from exc

    return cache_file


def build_access_token(relative_path: str) -> dict[str, str | int]:
    safe_path = assert_safe_relative_path(relative_path)
    ttl = settings.IMAGE_ACCESS_TOKEN_TTL
    token = create_image_access_token(
        safe_path,
        settings.IMAGE_ACCESS_SECRET,
        ttl_seconds=ttl,
    )
    return {
        "path": safe_path,
        "token": token,
        "expires_in": ttl,
    }


def content_type_for_path(relative_path: str) -> str:
    suffix = normalize_suffix(Path(relative_path).suffix.lstrip("."))
    return guess_mime(suffix)
