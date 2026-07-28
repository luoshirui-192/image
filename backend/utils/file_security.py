"""File upload validation, path security, and image access control (Step 9)."""
from __future__ import annotations

import hmac
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from utils.path_builder import (
    TEMPLATES_PREFIX,
    UPLOAD_PREFIX,
    is_valid_relative_path,
    is_valid_template_path,
    normalize_relative_path,
    normalize_suffix,
    project_root_from_upload_root,
    resolve_upload_file,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

ALLOWED_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "gif", "webp", "bmp"})

ALLOWED_MIME_TYPES = frozenset({
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/x-ms-bmp",
})

# Extension -> expected magic-byte signatures
MAGIC_SIGNATURES: dict[str, list[bytes]] = {
    "jpg": [b"\xff\xd8\xff"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],  # WEBP marker checked separately
    "bmp": [b"BM"],
}

BLOCKED_EXTENSIONS = frozenset({
    "exe", "dll", "bat", "cmd", "com", "msi", "scr",
    "php", "php3", "php4", "php5", "phtml", "jsp", "asp", "aspx",
    "sh", "bash", "zsh", "ps1", "vbs", "js", "html", "htm", "svg",
})

# Reject URL-encoded traversal, null bytes, backslashes in stored paths
UNSAFE_PATH_PATTERN = re.compile(r"(\.\.|%2e%2e|%252e|%00|\\)", re.IGNORECASE)

DEFAULT_TOKEN_TTL_SECONDS = 3600


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FileSecurityError(Exception):
    """Base class for file security violations."""


class UploadValidationError(FileSecurityError):
    """Raised when an upload fails extension/MIME/magic/size checks."""


class PathSecurityError(FileSecurityError):
    """Raised when a path is malformed or attempts directory traversal."""


class AccessDeniedError(FileSecurityError):
    """Raised when image access is not authorized."""


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidatedUpload:
    suffix: str
    mime_type: str
    size: int


def _read_head(source: bytes | BinaryIO, n: int = 32) -> bytes:
    if isinstance(source, bytes):
        return source[:n]
    pos = source.tell()
    try:
        return source.read(n)
    finally:
        source.seek(pos)


def detect_image_type(content_head: bytes) -> str | None:
    """Detect image type from magic bytes; returns normalized suffix or None."""
    if content_head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if content_head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content_head.startswith(b"GIF87a") or content_head.startswith(b"GIF89a"):
        return "gif"
    if (
        len(content_head) >= 12
        and content_head[:4] == b"RIFF"
        and content_head[8:12] == b"WEBP"
    ):
        return "webp"
    if content_head.startswith(b"BM"):
        return "bmp"
    return None


def extension_from_filename(filename: str) -> str:
    name = Path(filename).name
    if "." not in name:
        return ""
    return normalize_suffix(name.rsplit(".", 1)[-1])


def guess_mime(suffix: str) -> str:
    mapping = {
        "jpg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp",
    }
    return mapping.get(normalize_suffix(suffix), "application/octet-stream")


def validate_upload_file(
    filename: str,
    content: bytes | BinaryIO,
    *,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    declared_mime: str | None = None,
) -> ValidatedUpload:
    """
    Validate uploaded file: extension whitelist, blocked types, size, magic bytes, MIME.

    Raises UploadValidationError on any violation.
    """
    ext = extension_from_filename(filename)
    if not ext:
        raise UploadValidationError("文件缺少有效扩展名")
    if ext in BLOCKED_EXTENSIONS:
        raise UploadValidationError(f"禁止上传的文件类型: .{ext}")
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(f"仅允许上传图片: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    if isinstance(content, bytes):
        size = len(content)
        head = content[:32]
    else:
        pos = content.tell()
        data = content.read()
        size = len(data)
        head = data[:32]
        content.seek(pos)

    if size <= 0:
        raise UploadValidationError("文件内容为空")
    if size > max_bytes:
        raise UploadValidationError(f"文件大小超过限制 ({max_bytes // (1024 * 1024)} MB)")

    detected = detect_image_type(head)
    if detected is None:
        raise UploadValidationError("文件内容与图片格式不符（魔数校验失败）")

    normalized_ext = normalize_suffix(ext)
    if normalized_ext != detected:
        raise UploadValidationError(
            f"扩展名 .{ext} 与实际格式 .{detected} 不一致，疑似伪装文件"
        )

    mime = guess_mime(detected)
    if declared_mime and declared_mime.split(";")[0].strip().lower() not in ALLOWED_MIME_TYPES:
        raise UploadValidationError(f"不允许的 MIME 类型: {declared_mime}")

    return ValidatedUpload(suffix=detected, mime_type=mime, size=size)


# ---------------------------------------------------------------------------
# Path security
# ---------------------------------------------------------------------------


def contains_unsafe_path_segments(path: str) -> bool:
    """Detect traversal, null byte, encoded dots, or backslashes."""
    return UNSAFE_PATH_PATTERN.search(path) is not None


def get_upload_base_dir(upload_root: Path | str) -> Path:
    """Return resolved absolute path to the upload/ directory."""
    root = Path(upload_root).resolve()
    if root.name == UPLOAD_PREFIX:
        return root
    return root / UPLOAD_PREFIX


def assert_safe_relative_path(relative_path: str) -> str:
    """
    Validate relative path before DB storage or file access.

    Rules:
    - Must start with upload/ or templates/ prefix
    - No .., encoded dots, null bytes, backslashes
    - Must match layered path pattern from path_builder
    """
    if not relative_path or not str(relative_path).strip():
        raise PathSecurityError("路径不能为空")

    if contains_unsafe_path_segments(relative_path):
        raise PathSecurityError("路径包含非法字符或目录穿越片段")

    rel = normalize_relative_path(relative_path)
    if rel.startswith(f"{UPLOAD_PREFIX}/"):
        if not is_valid_relative_path(rel):
            raise PathSecurityError(f"路径格式不合法: {relative_path}")
        return rel

    if rel.startswith(f"{TEMPLATES_PREFIX}/"):
        if not is_valid_template_path(rel):
            raise PathSecurityError(f"模板路径格式不合法: {relative_path}")
        return rel

    raise PathSecurityError(
        f"路径必须以 {UPLOAD_PREFIX}/ 或 {TEMPLATES_PREFIX}/ 开头"
    )


def get_templates_base_dir(upload_root: Path | str) -> Path:
    """Return resolved absolute path to the templates/ directory."""
    return project_root_from_upload_root(upload_root) / TEMPLATES_PREFIX


def resolve_safe_upload_file(upload_root: Path | str, relative_path: str) -> Path:
    """
    Resolve relative path to absolute file path with traversal protection.

    After resolution, ensures the file path stays inside upload/ or templates/
    (guards against symlinks or unexpected path manipulation).
    """
    rel = assert_safe_relative_path(relative_path)
    abs_path = resolve_upload_file(upload_root, rel).resolve()
    if rel.startswith(f"{TEMPLATES_PREFIX}/"):
        base_dir = get_templates_base_dir(upload_root)
        scope = TEMPLATES_PREFIX
    else:
        base_dir = get_upload_base_dir(upload_root)
        scope = UPLOAD_PREFIX

    try:
        abs_path.relative_to(base_dir)
    except ValueError as exc:
        raise PathSecurityError(f"路径解析后超出 {scope} 目录范围") from exc

    return abs_path


def validate_template_file(
    filename: str,
    content: bytes | BinaryIO,
    *,
    allowed_suffixes: set[str] | frozenset[str],
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> ValidatedUpload:
    """
    Validate fingerprint template upload (ISO FMR / algorithm-specific).

    Allowed suffixes come from layer-type config (e.g. bidiso, neuiso).
    """
    ext = extension_from_filename(filename)
    if not ext:
        raise UploadValidationError("文件缺少有效扩展名")
    if ext in BLOCKED_EXTENSIONS:
        raise UploadValidationError(f"禁止上传的文件类型: .{ext}")

    allowed = {normalize_suffix(s) for s in allowed_suffixes}
    if ext not in allowed:
        raise UploadValidationError(
            f"不支持的模板类型 .{ext}，允许: {', '.join(sorted(allowed))}"
        )

    if isinstance(content, bytes):
        size = len(content)
        head = content[:32]
    else:
        pos = content.tell()
        data = content.read()
        size = len(data)
        head = data[:32]
        content.seek(pos)

    if size <= 0:
        raise UploadValidationError("文件内容为空")
    if size > max_bytes:
        raise UploadValidationError(f"文件大小超过限制 ({max_bytes // (1024 * 1024)} MB)")

    # ISO 19794-2 Finger Minutiae Record magic: FMR\0
    if not head.startswith(b"FMR\x00"):
        raise UploadValidationError("模板内容不是有效的 ISO FMR 特征（缺少 FMR 头）")

    return ValidatedUpload(
        suffix=ext,
        mime_type="application/octet-stream",
        size=size,
    )


# ---------------------------------------------------------------------------
# Image access token (for unauthenticated preview/download links)
# ---------------------------------------------------------------------------


def _sign_payload(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def create_image_access_token(
    relative_path: str,
    secret: str,
    *,
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    now: int | None = None,
) -> str:
    """
    Create HMAC-signed token binding to a specific image path and expiry.

    Format: {expires_at}.{signature}
    """
    rel = assert_safe_relative_path(relative_path)
    if not secret:
        raise ValueError("secret is required")

    expires_at = (now if now is not None else int(time.time())) + ttl_seconds
    payload = f"{rel}|{expires_at}"
    signature = _sign_payload(payload, secret)
    return f"{expires_at}.{signature}"


def verify_image_access_token(
    relative_path: str,
    token: str,
    secret: str,
    *,
    now: int | None = None,
) -> bool:
    """Return True if token is valid for the given path and not expired."""
    if not token or not secret:
        return False

    try:
        rel = assert_safe_relative_path(relative_path)
        expires_str, signature = token.rsplit(".", 1)
        expires_at = int(expires_str)
    except (ValueError, PathSecurityError):
        return False

    current = now if now is not None else int(time.time())
    if current > expires_at:
        return False

    payload = f"{rel}|{expires_at}"
    expected = _sign_payload(payload, secret)
    return hmac.compare_digest(expected, signature)


def check_image_access_allowed(
    relative_path: str,
    *,
    is_authenticated: bool,
    access_token: str | None = None,
    secret: str = "",
) -> None:
    """
    Enforce image access policy:
    - Authenticated users: allowed
    - Anonymous users: must provide valid access_token
    """
    assert_safe_relative_path(relative_path)

    if is_authenticated:
        return

    if access_token and secret and verify_image_access_token(relative_path, access_token, secret):
        return

    raise AccessDeniedError("未登录且访问令牌无效，无法读取图片")
