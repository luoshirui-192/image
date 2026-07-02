"""Image upload and batch import business logic — Step 12."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from django.conf import settings
from PIL import Image

from images.file_service import thumb_cache_path
from images.models import ImageCategory, ImageInfo
from utils.db_time import fetch_db_now
from utils.file_security import UploadValidationError, validate_upload_file
from utils.path_builder import build_relative_path, ensure_parent_dir, normalize_suffix

logger = logging.getLogger(__name__)

IMAGE_GLOB_SUFFIXES = ("*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.bmp")


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


def _resolve_category_id(category_id: int | None) -> int:
    if category_id is None:
        return 0
    if category_id <= 0:
        return 0
    if not ImageCategory.objects.filter(id=category_id).exists():
        raise ValueError(f"分类不存在: id={category_id}")
    return category_id


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

    if normalize_suffix(Path(old_path).suffix.lstrip(".")) == suffix:
        abs_path = ensure_parent_dir(settings.UPLOAD_ROOT, old_path)
        abs_path.write_bytes(content)
        relative_path = old_path
    else:
        now = fetch_db_now()
        relative_path = build_relative_path(cat_id, suffix, when=now)
        abs_path = ensure_parent_dir(settings.UPLOAD_ROOT, relative_path)
        abs_path.write_bytes(content)
        if old_path and old_path != relative_path:
            try:
                old_abs = ensure_parent_dir(settings.UPLOAD_ROOT, old_path)
                if old_abs.is_file():
                    old_abs.unlink()
                _invalidate_thumbnail(old_path)
            except OSError:
                logger.warning("failed to remove old file %s", old_path, exc_info=True)

    _invalidate_thumbnail(relative_path)

    existing.image_name = Path(filename).name
    existing.image_path = relative_path
    existing.image_width = width
    existing.image_height = height
    existing.file_size = validated.size
    existing.file_suffix = suffix
    existing.file_hash = content_hash
    existing.upload_user = upload_user
    existing.category_id = cat_id or None
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
    abs_path = ensure_parent_dir(settings.UPLOAD_ROOT, relative_path)
    abs_path.write_bytes(content)

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
        category_id=cat_id or None,
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
        duplicates: list[dict] = []
        for name, content, validated, _mime, _err in prepared:
            if validated is None:
                continue
            content_hash = compute_content_hash(content)
            existing = find_duplicate_image(filename=name, content_hash=content_hash)
            if existing:
                duplicates.append({"filename": name, "existing_id": existing.id, "existing": existing})
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


def _resolve_import_directory(directory: str) -> Path:
    raw = Path(directory).expanduser()
    if not raw.is_absolute():
        raw = Path(settings.IMPORT_SCAN_ROOT) / raw

    resolved = raw.resolve()
    scan_root = Path(settings.IMPORT_SCAN_ROOT).resolve()

    try:
        resolved.relative_to(scan_root)
    except ValueError as exc:
        raise ValueError(f"导入目录必须在 {scan_root} 之下") from exc

    if not resolved.is_dir():
        raise ValueError("导入路径不是有效目录")

    upload_root = Path(settings.UPLOAD_ROOT).resolve()
    try:
        resolved.relative_to(upload_root)
        raise ValueError("不能从 upload 目录导入（请使用上传接口）")
    except ValueError:
        pass

    return resolved


def _iter_import_files(directory: Path, *, recursive: bool) -> list[Path]:
    files: list[Path] = []
    if recursive:
        for pattern in IMAGE_GLOB_SUFFIXES:
            files.extend(directory.rglob(pattern))
    else:
        for pattern in IMAGE_GLOB_SUFFIXES:
            files.extend(directory.glob(pattern))
    return sorted({p.resolve() for p in files if p.is_file()})


def import_images_from_directory(
    directory: str,
    *,
    upload_user: str,
    category_id: int | None = None,
    tags: str = "",
    recursive: bool = False,
    overwrite: bool = False,
) -> list[UploadResult]:
    """Scan a server-local folder and import image files into upload storage."""
    overwrite = _parse_overwrite(overwrite)
    source_dir = _resolve_import_directory(directory)
    file_paths = _iter_import_files(source_dir, recursive=recursive)

    if not file_paths:
        return []

    prepared: list[tuple[Path, bytes]] = []
    for file_path in file_paths:
        prepared.append((file_path, file_path.read_bytes()))

    if not overwrite:
        duplicates: list[dict] = []
        for file_path, content in prepared:
            content_hash = compute_content_hash(content)
            existing = find_duplicate_image(filename=file_path.name, content_hash=content_hash)
            if existing:
                duplicates.append({"filename": file_path.name, "existing_id": existing.id, "existing": existing})
        if duplicates:
            raise DuplicateBatchError(duplicates)

    results: list[UploadResult] = []
    for file_path, content in prepared:
        try:
            existing_before = find_duplicate_image(
                filename=file_path.name,
                content_hash=compute_content_hash(content),
            )
            record = save_image_bytes(
                filename=file_path.name,
                content=content,
                upload_user=upload_user,
                category_id=category_id,
                tags=tags,
                overwrite=overwrite,
            )
            results.append(
                UploadResult(
                    success=True,
                    filename=file_path.name,
                    image=record,
                    overwritten=bool(existing_before and overwrite),
                )
            )
        except (UploadValidationError, ValueError) as exc:
            results.append(UploadResult(success=False, filename=file_path.name, error=str(exc)))
        except Exception as exc:
            logger.exception("import failed for %s", file_path)
            results.append(UploadResult(success=False, filename=file_path.name, error=f"导入失败: {exc}"))

    return results
