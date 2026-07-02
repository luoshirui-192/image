#!/usr/bin/env python3
"""Security checks for Step 9: upload validation, path traversal, access tokens."""
from __future__ import annotations

import sys
import time
from io import BytesIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from utils.file_security import (  # noqa: E402
    AccessDeniedError,
    UploadValidationError,
    PathSecurityError,
    check_image_access_allowed,
    create_image_access_token,
    detect_image_type,
    resolve_safe_upload_file,
    validate_upload_file,
    verify_image_access_token,
)
from utils.path_builder import build_relative_path  # noqa: E402
from utils.security_test_fixtures import (  # noqa: E402
    blocked_script_filename,
    php_disguised_upload_bytes,
    png_magic_head,
)

PNG_BYTES = png_magic_head()


def test_magic_and_extension() -> None:
    validate_upload_file("a.png", PNG_BYTES)
    try:
        validate_upload_file(blocked_script_filename(), php_disguised_upload_bytes(variant="echo"))
        raise AssertionError("php disguise should fail")
    except UploadValidationError:
        pass
    try:
        validate_upload_file("empty.jpg", b"")
        raise AssertionError("empty should fail")
    except UploadValidationError:
        pass
    assert detect_image_type(PNG_BYTES) == "png"


def test_path_traversal() -> None:
    upload_root = PROJECT_ROOT / "upload"
    good = build_relative_path(1, "jpg", file_uuid="550e8400-e29b-41d4-a716-446655440001", date_str="20260630")
    resolve_safe_upload_file(upload_root, good)

    bad_paths = [
        "upload/../etc/passwd",
        "upload/20260630/1/../../secret.jpg",
        "upload/%2e%2e/admin",
        "../../image_db.sql",
    ]
    for bad in bad_paths:
        try:
            resolve_safe_upload_file(upload_root, bad)
            raise AssertionError(f"should reject: {bad}")
        except PathSecurityError:
            pass


def test_access_token() -> None:
    secret = "test-secret-key"
    path = build_relative_path(2, "png", file_uuid="550e8400-e29b-41d4-a716-446655440001", date_str="20260630")
    now = int(time.time())
    token = create_image_access_token(path, secret, ttl_seconds=300, now=now)
    assert verify_image_access_token(path, token, secret, now=now + 100)
    assert not verify_image_access_token(path, token, secret, now=now + 301)

    check_image_access_allowed(path, is_authenticated=True)
    assert verify_image_access_token(path, token, secret, now=now + 100)
    check_image_access_allowed(path, is_authenticated=False, access_token=token, secret=secret)

    try:
        check_image_access_allowed(path, is_authenticated=False)
        raise AssertionError("anonymous without token should fail")
    except AccessDeniedError:
        pass


def main() -> int:
    test_magic_and_extension()
    test_path_traversal()
    test_access_token()
    print("file_security tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
