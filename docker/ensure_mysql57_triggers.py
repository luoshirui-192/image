"""Ensure image_info triggers are MySQL 5.7 strict-mode safe (no '0000-00-00')."""
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
        print("[triggers] skip (not mysql)")
        return 0

    statements = [
        "DROP TRIGGER IF EXISTS `trg_image_info_update_time`",
        "DROP TRIGGER IF EXISTS `trg_image_info_insert_time`",
        """
        CREATE TRIGGER `trg_image_info_update_time` BEFORE UPDATE ON `image_info`
        FOR EACH ROW
        BEGIN
          SET NEW.update_time = CURRENT_TIMESTAMP;
        END
        """,
        """
        CREATE TRIGGER `trg_image_info_insert_time` BEFORE INSERT ON `image_info`
        FOR EACH ROW
        BEGIN
          IF NEW.upload_time IS NULL THEN
            SET NEW.upload_time = CURRENT_TIMESTAMP;
          END IF;
          IF NEW.update_time IS NULL THEN
            SET NEW.update_time = NEW.upload_time;
          END IF;
        END
        """,
    ]

    with connection.cursor() as cursor:
        for sql in statements:
            cursor.execute(sql)

    print("[ok] mysql57 image_info triggers ensured")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[warn] trigger ensure failed: {exc}", file=sys.stderr)
        raise SystemExit(0)
