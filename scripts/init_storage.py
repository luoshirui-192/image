#!/usr/bin/env python3
"""Initialize upload storage and verify write permission."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = PROJECT_ROOT / "upload"
THUMB_CACHE_DIR = PROJECT_ROOT / "backend" / "thumb_cache"

sys.path.insert(0, str(PROJECT_ROOT / "backend"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from utils.path_builder import build_relative_path  # noqa: E402
from utils.storage import get_image_storage, reset_image_storage_cache  # noqa: E402


def main() -> int:
    THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    reset_image_storage_cache()
    storage = get_image_storage()

    ok, detail = storage.check_writable()
    if not ok:
        print(f"ERROR: storage not writable: {detail}", file=sys.stderr)
        return 1

    sample_rel = build_relative_path(category_id=1, suffix="jpg")
    probe_key = sample_rel.replace(".jpg", ".probe")
    storage.write_bytes(probe_key, b"ok")
    storage.delete(probe_key)

    print(f"storage backend:  {storage.backend_name}")
    print(f"storage target:   {detail}")
    print(f"thumb cache root: {THUMB_CACHE_DIR}")
    print(f"sample path:      {sample_rel}")
    if settings.STORAGE_BACKEND == "local":
        print(f"upload root:      {settings.UPLOAD_ROOT}")
    else:
        print(f"minio endpoint:   {settings.MINIO_ENDPOINT}")
        print(f"minio bucket:     {settings.MINIO_BUCKET}")
        print(f"minio prefix:     {settings.MINIO_PREFIX}")
    print("storage init OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
