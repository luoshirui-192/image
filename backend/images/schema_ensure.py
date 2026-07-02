"""Ensure optional DB columns exist (legacy deployments without full migrations)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def ensure_file_hash_column() -> None:
    """Add image_info.file_hash when missing (duplicate detection)."""
    from django.db import connection

    if connection.vendor != "mysql":
        return

    try:
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
                logger.info("added image_info.file_hash column")

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
                logger.info("added idx_file_hash index")
    except Exception:
        logger.warning("ensure file_hash column failed", exc_info=True)
