"""Walk a local folder, store images via get_image_storage (MinIO/local), write paths to image_info."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from images.services import DuplicateImageError, save_image_bytes
from utils.file_security import ALLOWED_EXTENSIONS, UploadValidationError
from utils.path_builder import normalize_suffix
from utils.storage import get_image_storage

logger = logging.getLogger(__name__)


class FolderIngestError(Exception):
    """Raised when folder ingest cannot start."""


@dataclass
class FolderIngestItemResult:
    source_path: str
    success: bool
    skipped: bool = False
    image_id: int | None = None
    image_path: str = ""
    error: str = ""


@dataclass
class FolderIngestResult:
    root: str
    total_found: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    dry_run: bool = False
    storage_backend: str = ""
    items: list[FolderIngestItemResult] = field(default_factory=list)


def iter_image_files(root: Path, *, recursive: bool = True) -> list[Path]:
    """Collect image files under root (sorted), filtered by ALLOWED_EXTENSIONS."""
    if not root.exists():
        raise FolderIngestError(f"目录不存在: {root}")
    if not root.is_dir():
        raise FolderIngestError(f"不是目录: {root}")

    paths: list[Path] = []
    if recursive:
        candidates = root.rglob("*")
    else:
        candidates = root.iterdir()

    for path in candidates:
        if not path.is_file():
            continue
        suffix = normalize_suffix(path.suffix.lstrip("."))
        if suffix in ALLOWED_EXTENSIONS:
            paths.append(path)
    return sorted(paths, key=lambda p: str(p).lower())


def ingest_folder_images(
    root: str | Path,
    *,
    upload_user: str,
    category_id: int | None = None,
    tags: str = "",
    recursive: bool = True,
    skip_existing: bool = True,
    overwrite: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
) -> FolderIngestResult:
    """
    Traverse a folder of images → write bytes to storage (MinIO when configured)
    → insert/update image_info.image_path with the relative storage path.

    Same storage path convention as web upload / fingerprint import:
        upload/{YYYYMMDD}/{category_id}/{uuid}.{ext}
    """
    root_path = Path(root).expanduser().resolve()
    files = iter_image_files(root_path, recursive=recursive)
    if limit is not None and limit >= 0:
        files = files[:limit]

    storage = get_image_storage()
    result = FolderIngestResult(
        root=str(root_path),
        total_found=len(files),
        dry_run=dry_run,
        storage_backend=getattr(storage, "backend_name", "unknown"),
    )

    if not files:
        return result

    upload_user = (upload_user or "").strip() or "folder_ingest"
    tags = (tags or "").strip()[:500]

    for path in files:
        rel_src = str(path.relative_to(root_path))
        if dry_run:
            result.succeeded += 1
            result.items.append(
                FolderIngestItemResult(
                    source_path=rel_src,
                    success=True,
                    image_path="(dry-run)",
                )
            )
            continue

        try:
            content = path.read_bytes()
            max_bytes = getattr(settings, "MAX_UPLOAD_SIZE_BYTES", 20 * 1024 * 1024)
            if len(content) > max_bytes:
                raise UploadValidationError(f"文件过大: {len(content)} > {max_bytes}")

            try:
                image = save_image_bytes(
                    filename=path.name,
                    content=content,
                    upload_user=upload_user,
                    category_id=category_id,
                    tags=tags,
                    overwrite=overwrite,
                )
            except DuplicateImageError as exc:
                if skip_existing and not overwrite:
                    existing = exc.existing
                    result.skipped += 1
                    result.items.append(
                        FolderIngestItemResult(
                            source_path=rel_src,
                            success=True,
                            skipped=True,
                            image_id=existing.id,
                            image_path=existing.image_path,
                            error="duplicate skipped",
                        )
                    )
                    continue
                result.failed += 1
                result.items.append(
                    FolderIngestItemResult(
                        source_path=rel_src,
                        success=False,
                        image_id=exc.existing.id if exc.existing else None,
                        image_path=exc.existing.image_path if exc.existing else "",
                        error="duplicate exists (use --overwrite or default skip)",
                    )
                )
                continue

            result.succeeded += 1
            result.items.append(
                FolderIngestItemResult(
                    source_path=rel_src,
                    success=True,
                    image_id=image.id,
                    image_path=image.image_path,
                )
            )
        except (UploadValidationError, FolderIngestError, OSError, ValueError) as exc:
            result.failed += 1
            result.items.append(
                FolderIngestItemResult(
                    source_path=rel_src,
                    success=False,
                    error=str(exc)[:500],
                )
            )
            logger.warning("folder ingest failed path=%s: %s", path, exc)
        except Exception as exc:
            result.failed += 1
            result.items.append(
                FolderIngestItemResult(
                    source_path=rel_src,
                    success=False,
                    error=f"保存失败: {exc}"[:500],
                )
            )
            logger.exception("folder ingest unexpected error path=%s", path)

    return result
