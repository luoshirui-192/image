#!/usr/bin/env python3
"""Initialize upload storage directories and verify write permission (Step 8)."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = PROJECT_ROOT / "upload"
THUMB_CACHE_DIR = PROJECT_ROOT / "backend" / "thumb_cache"

# Ensure backend.utils import works when run as script
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from utils.path_builder import build_relative_path, ensure_parent_dir, resolve_upload_file  # noqa: E402


def main() -> int:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Smoke test: create a sample path layout without leaving a real image
    sample_rel = build_relative_path(category_id=1, suffix="jpg")
    sample_abs = ensure_parent_dir(UPLOAD_DIR, sample_rel)
    probe = sample_abs.with_suffix(".probe")
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()

    resolved = resolve_upload_file(UPLOAD_DIR, sample_rel)
    if resolved.parent != sample_abs.parent:
        print("ERROR: path resolution mismatch", file=sys.stderr)
        return 1

    print(f"upload root:      {UPLOAD_DIR}")
    print(f"thumb cache root: {THUMB_CACHE_DIR}")
    print(f"sample path:      {sample_rel}")
    print(f"sample abs dir:   {sample_abs.parent}")
    print("storage init OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
