"""Ensure image_info.file_hash column exists (duplicate detection)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main() -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    import django

    django.setup()

    from django.db import connection

    if connection.vendor != "mysql":
        print("[file_hash] skip (not mysql)")
        return 0

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'image_info'
              AND COLUMN_NAME = 'file_hash'
            """
        )
        exists = cursor.fetchone()[0]
        if not exists:
            cursor.execute(
                """
                ALTER TABLE `image_info`
                ADD COLUMN `file_hash` varchar(64) NOT NULL DEFAULT ''
                COMMENT '文件内容 SHA256'
                AFTER `file_suffix`
                """
            )
            print("[ok] added image_info.file_hash column")

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'image_info'
              AND INDEX_NAME = 'idx_file_hash'
            """
        )
        idx_exists = cursor.fetchone()[0]
        if not idx_exists:
            cursor.execute("ALTER TABLE `image_info` ADD INDEX `idx_file_hash` (`file_hash`)")
            print("[ok] added idx_file_hash index")

    print("[ok] file_hash column ensured")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[warn] file_hash ensure failed: {exc}", file=sys.stderr)
        raise SystemExit(0)
