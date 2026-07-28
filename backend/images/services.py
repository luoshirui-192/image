"""Image upload business logic — Step 12."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from django.conf import settings
from PIL import Image

from images.category_service import resolve_category_id
from images.models import ImageInfo
from images.file_service import thumb_cache_path
from utils.db_time import fetch_db_now
from utils.file_security import UploadValidationError, validate_upload_file
from utils.path_builder import build_relative_path, normalize_suffix
from utils.storage import get_image_storage

logger = logging.getLogger(__name__)


class DuplicateImageError(Exception):
    """Raised when uploading a duplicate image without overwrite permission."""

    def __init__(self, existing: ImageInfo, *, filename: str):
        self.existing = existing
        self.filename = filename
        super().__init__(f"图片已存在: {filename}")


class DuplicateBatchError(Exception):
    """Raised when a batch contains duplicates and overwrite is not enabled."""

    def __init__(self, duplicates: list[dict]):
        self.duplicates = duplicates
        super().__init__("存在重复图片")


@dataclass
class UploadResult:
    success: bool
    filename: str
    image: ImageInfo | None = None
    error: str = ""
    duplicate: bool = False
    existing_image: ImageInfo | None = None
    overwritten: bool = False


def compute_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def find_duplicate_image(*, filename: str, content_hash: str) -> ImageInfo | None:
    """Find an active record with the same content hash or filename."""
    active = ImageInfo.objects.filter(is_delete=0)
    if content_hash:
        match = active.filter(file_hash=content_hash).first()
        if match:
            return match
    name = Path(filename).name
    return active.filter(image_name=name).first()


def _collect_batch_duplicates(
    items: list[tuple[str, bytes]],
) -> list[dict]:
    """Detect duplicates against DB and within the same batch."""
    duplicates: list[dict] = []
    seen_hashes: dict[str, str] = {}
    seen_names: set[str] = set()

    for name, content in items:
        content_hash = compute_content_hash(content)
        basename = Path(name).name

        existing = find_duplicate_image(filename=name, content_hash=content_hash)
        if existing:
            duplicates.append({"filename": name, "existing_id": existing.id, "existing": existing})
            continue

        if content_hash in seen_hashes:
            duplicates.append(
                {
                    "filename": name,
                    "existing_id": None,
                    "existing": None,
                    "batch_duplicate_of": seen_hashes[content_hash],
                }
            )
            continue

        if basename in seen_names:
            duplicates.append(
                {
                    "filename": name,
                    "existing_id": None,
                    "existing": None,
                    "batch_duplicate_of": basename,
                }
            )
            continue

        seen_hashes[content_hash] = name
        seen_names.add(basename)

    return duplicates


def _resolve_category_id(category_id: int | None) -> int:
    return resolve_category_id(category_id)


def _read_image_dimensions(content: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(content)) as img:
        return img.size


def _invalidate_thumbnail(relative_path: str) -> None:
    try:
        thumb_cache_path(relative_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("failed to remove thumb cache for %s", relative_path, exc_info=True)


def _overwrite_existing_image(
    existing: ImageInfo,
    *,
    filename: str,
    content: bytes,
    validated,
    upload_user: str,
    category_id: int | None,
    tags: str,
) -> ImageInfo:
    """Replace file on disk and update metadata for an existing record."""
    cat_id = _resolve_category_id(category_id)
    width, height = _read_image_dimensions(content)
    content_hash = compute_content_hash(content)
    old_path = existing.image_path
    suffix = validated.suffix

    storage = get_image_storage()
    if normalize_suffix(Path(old_path).suffix.lstrip(".")) == suffix:
        storage.write_bytes(old_path, content)
        relative_path = old_path
    else:
        now = fetch_db_now()
        relative_path = build_relative_path(cat_id, suffix, when=now)
        storage.write_bytes(relative_path, content)
        if old_path and old_path != relative_path:
            deleted, _ = storage.delete(old_path)
            if deleted:
                _invalidate_thumbnail(old_path)
            elif old_path:
                logger.warning("failed to remove old file %s", old_path)

    _invalidate_thumbnail(relative_path)

    existing.image_name = Path(filename).name
    existing.image_path = relative_path
    existing.image_width = width
    existing.image_height = height
    existing.file_size = validated.size
    existing.file_suffix = suffix
    existing.file_hash = content_hash
    existing.upload_user = upload_user
    existing.category_id = cat_id
    existing.tags = (tags or "").strip()[:500]
    existing.save(
        update_fields=[
            "image_name",
            "image_path",
            "image_width",
            "image_height",
            "file_size",
            "file_suffix",
            "file_hash",
            "upload_user",
            "category_id",
            "tags",
        ]
    )
    return existing


def save_image_bytes(
    *,
    filename: str,
    content: bytes,
    upload_user: str,
    category_id: int | None = None,
    tags: str = "",
    declared_mime: str | None = None,
    overwrite: bool = False,
) -> ImageInfo:
    """Validate, store file on disk, and insert or update image_info row."""
    validated = validate_upload_file(
        filename,
        content,
        max_bytes=settings.MAX_UPLOAD_SIZE_BYTES,
        declared_mime=declared_mime,
    )
    content_hash = compute_content_hash(content)
    existing = find_duplicate_image(filename=filename, content_hash=content_hash)

    if existing and not overwrite:
        raise DuplicateImageError(existing, filename=filename)

    if existing and overwrite:
        return _overwrite_existing_image(
            existing,
            filename=filename,
            content=content,
            validated=validated,
            upload_user=upload_user,
            category_id=category_id,
            tags=tags,
        )

    cat_id = _resolve_category_id(category_id)
    width, height = _read_image_dimensions(content)

    now = fetch_db_now()
    relative_path = build_relative_path(cat_id, validated.suffix, when=now)
    get_image_storage().write_bytes(relative_path, content)

    record = ImageInfo.objects.create(
        image_name=Path(filename).name,
        image_path=relative_path,
        image_width=width,
        image_height=height,
        file_size=validated.size,
        file_suffix=validated.suffix,
        file_hash=content_hash,
        upload_time=now,
        update_time=now,
        upload_user=upload_user,
        is_delete=0,
        category_id=cat_id,
        tags=(tags or "").strip()[:500],
    )
    return record


def save_image_bytes_for_migration(
    *,
    filename: str,
    content: bytes,
    upload_user: str,
    category_id: int | None = None,
    tags: str = "",
    declared_mime: str | None = None,
) -> ImageInfo:
    """Fast upload path for BLOB migration — skips duplicate lookup and optional dimension read."""
    validated = validate_upload_file(
        filename,
        content,
        max_bytes=settings.MAX_UPLOAD_SIZE_BYTES,
        declared_mime=declared_mime,
    )
    skip_dimensions = getattr(settings, "BLOB_MIGRATION_SKIP_DIMENSIONS", True)
    if skip_dimensions:
        width, height = 0, 0
    else:
        width, height = _read_image_dimensions(content)

    cat_id = _resolve_category_id(category_id)
    content_hash = compute_content_hash(content)

    now = fetch_db_now()
    relative_path = build_relative_path(cat_id, validated.suffix, when=now)
    get_image_storage().write_bytes(relative_path, content)

    record = ImageInfo.objects.create(
        image_name=Path(filename).name,
        image_path=relative_path,
        image_width=width,
        image_height=height,
        file_size=validated.size,
        file_suffix=validated.suffix,
        file_hash=content_hash,
        upload_time=now,
        update_time=now,
        upload_user=upload_user,
        is_delete=0,
        category_id=cat_id,
        tags=(tags or "").strip()[:500],
    )
    return record


def save_uploaded_file(
    uploaded_file,
    *,
    upload_user: str,
    category_id: int | None = None,
    tags: str = "",
    overwrite: bool = False,
) -> ImageInfo:
    content = uploaded_file.read()
    return save_image_bytes(
        filename=getattr(uploaded_file, "name", "upload.jpg"),
        content=content,
        upload_user=upload_user,
        category_id=category_id,
        tags=tags,
        declared_mime=getattr(uploaded_file, "content_type", None),
        overwrite=overwrite,
    )


def _parse_overwrite(value) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).lower() in {"1", "true", "yes", "on"}


def save_uploaded_files(
    uploaded_files,
    *,
    upload_user: str,
    category_id: int | None = None,
    tags: str = "",
    overwrite: bool = False,
) -> list[UploadResult]:
    """Save multiple uploads; reject entire batch if duplicates found without overwrite."""
    overwrite = _parse_overwrite(overwrite)
    prepared: list[tuple[str, bytes, object | None, str | None, str]] = []

    for uploaded_file in uploaded_files:
        name = getattr(uploaded_file, "name", "unknown")
        content = uploaded_file.read()
        try:
            validated = validate_upload_file(
                name,
                content,
                max_bytes=settings.MAX_UPLOAD_SIZE_BYTES,
                declared_mime=getattr(uploaded_file, "content_type", None),
            )
            prepared.append((name, content, validated, getattr(uploaded_file, "content_type", None), ""))
        except UploadValidationError as exc:
            prepared.append((name, content, None, None, str(exc)))

    if not overwrite:
        batch_items = [(name, content) for name, content, validated, _mime, _err in prepared if validated is not None]
        duplicates = _collect_batch_duplicates(batch_items)
        if duplicates:
            raise DuplicateBatchError(duplicates)

    results: list[UploadResult] = []
    for name, content, validated, declared_mime, validation_error in prepared:
        if validated is None:
            results.append(UploadResult(success=False, filename=name, error=validation_error))
            continue
        try:
            existing_before = find_duplicate_image(
                filename=name,
                content_hash=compute_content_hash(content),
            )
            record = save_image_bytes(
                filename=name,
                content=content,
                upload_user=upload_user,
                category_id=category_id,
                tags=tags,
                declared_mime=declared_mime,
                overwrite=overwrite,
            )
            results.append(
                UploadResult(
                    success=True,
                    filename=name,
                    image=record,
                    overwritten=bool(existing_before and overwrite),
                )
            )
        except (UploadValidationError, ValueError) as exc:
            results.append(UploadResult(success=False, filename=name, error=str(exc)))
        except Exception as exc:
            logger.exception("upload failed for %s", name)
            results.append(UploadResult(success=False, filename=name, error=f"保存失败: {exc}"))

    return results
