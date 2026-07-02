"""
Upload path builder — layered storage layout (Step 8).

Relative path format:
    upload/{YYYYMMDD}/{category_id}/{uuid}.{suffix}

Example:
    upload/20260630/2/550e8400-e29b-41d4-a716-446655440001.jpg
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

UPLOAD_PREFIX = "upload"

# upload/20260630/2/550e8400-e29b-41d4-a716-446655440001.jpg
RELATIVE_PATH_RE = re.compile(
    r"^upload/(\d{8})/(\d+)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.([a-z0-9]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedUploadPath:
    date_str: str
    category_id: int
    file_uuid: str
    suffix: str

    @property
    def relative_path(self) -> str:
        return build_relative_path(self.category_id, self.suffix, file_uuid=self.file_uuid, date_str=self.date_str)


def normalize_suffix(suffix: str) -> str:
    """Normalize file extension to lowercase without dot."""
    value = suffix.strip().lstrip(".").lower()
    if value == "jpeg":
        return "jpg"
    return value


def format_date_str(when: date | datetime | None = None) -> str:
    """Return YYYYMMDD for directory naming (Asia/Shanghai local calendar day)."""
    if when is None:
        when = datetime.now(SHANGHAI)
    if isinstance(when, datetime):
        if when.tzinfo is None:
            when = when.replace(tzinfo=SHANGHAI)
        else:
            when = when.astimezone(SHANGHAI)
        when = when.date()
    return when.strftime("%Y%m%d")


def build_relative_path(
    category_id: int,
    suffix: str,
    *,
    file_uuid: str | None = None,
    date_str: str | None = None,
    when: date | datetime | None = None,
) -> str:
    """
    Build DB-stored relative path under upload/.

    Args:
        category_id: image_category.id; use 0 if uncategorized.
        suffix: file extension, with or without leading dot.
        file_uuid: optional fixed UUID (for tests); random if omitted.
        date_str: optional YYYYMMDD; derived from `when` or today if omitted.
        when: date used when date_str is not provided.
    """
    if category_id < 0:
        raise ValueError("category_id must be non-negative")

    ext = normalize_suffix(suffix)
    if not ext:
        raise ValueError("suffix is required")

    uid = file_uuid or str(uuid.uuid4())
    day = date_str or format_date_str(when)
    if not re.fullmatch(r"\d{8}", day):
        raise ValueError("date_str must be YYYYMMDD")

    return f"{UPLOAD_PREFIX}/{day}/{category_id}/{uid}.{ext}"


def build_absolute_path(upload_root: Path | str, relative_path: str) -> Path:
    """Alias for resolve_upload_file."""
    return resolve_upload_file(upload_root, relative_path)


def resolve_upload_file(upload_root: Path | str, relative_path: str) -> Path:
    """
    Resolve absolute file path from DB relative path.

    upload_root points to the `upload/` directory itself; relative_path includes `upload/` prefix.
    """
    rel = normalize_relative_path(relative_path)
    if not is_valid_relative_path(rel):
        raise ValueError(f"invalid upload relative path: {relative_path}")

    # relative_path: upload/20260630/2/uuid.jpg -> project_root/upload/20260630/2/uuid.jpg
    root = Path(upload_root).resolve()
    if root.name == UPLOAD_PREFIX:
        project_root = root.parent
    else:
        project_root = root

    return project_root.joinpath(*rel.split("/"))


def ensure_parent_dir(upload_root: Path | str, relative_path: str) -> Path:
    """Create parent directories for the target file; return absolute file path."""
    file_path = resolve_upload_file(upload_root, relative_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    return file_path


def normalize_relative_path(path: str) -> str:
    """Normalize slashes and strip leading slash."""
    return path.replace("\\", "/").lstrip("/")


def is_valid_relative_path(relative_path: str) -> bool:
    """Validate path matches upload/{date}/{category_id}/{uuid}.{suffix}."""
    return RELATIVE_PATH_RE.match(normalize_relative_path(relative_path)) is not None


def parse_relative_path(relative_path: str) -> ParsedUploadPath:
    """Parse relative path into components."""
    rel = normalize_relative_path(relative_path)
    match = RELATIVE_PATH_RE.match(rel)
    if not match:
        raise ValueError(f"cannot parse upload path: {relative_path}")

    date_str, category_id, file_uuid, suffix = match.groups()
    return ParsedUploadPath(
        date_str=date_str,
        category_id=int(category_id),
        file_uuid=file_uuid.lower(),
        suffix=normalize_suffix(suffix),
    )


def list_date_dirs(upload_root: Path | str) -> list[str]:
    """List YYYYMMDD directories under upload root (for backup/cleanup jobs)."""
    root = Path(upload_root)
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and re.fullmatch(r"\d{8}", p.name)
    )
