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


def ensure_migration_tables() -> None:
    """Create blob_migration_source and image_source_map when missing."""
    from django.db import connection

    if connection.vendor != "mysql":
        return

    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS `blob_migration_source` (
          `id` int(10) UNSIGNED NOT NULL AUTO_INCREMENT,
          `name` varchar(100) NOT NULL DEFAULT '',
          `source_table` varchar(64) NOT NULL,
          `source_pk_column` varchar(64) NOT NULL DEFAULT 'id',
          `blob_column` varchar(64) NOT NULL,
          `name_column` varchar(64) NOT NULL DEFAULT '',
          `suffix_column` varchar(64) NOT NULL DEFAULT '',
          `category_id` int(10) UNSIGNED NOT NULL,
          `upload_user` varchar(100) NOT NULL DEFAULT 'migration',
          `tags` varchar(500) NOT NULL DEFAULT '',
          `where_clause` varchar(500) NOT NULL DEFAULT '',
          `db_alias` varchar(32) NOT NULL DEFAULT 'default',
          `enabled` tinyint(4) NOT NULL DEFAULT 1,
          `last_run_at` datetime NULL DEFAULT NULL,
          `create_time` datetime NULL DEFAULT NULL,
          PRIMARY KEY (`id`),
          KEY `idx_enabled`(`enabled`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='BLOB 迁移源配置'
        """,
        """
        CREATE TABLE IF NOT EXISTS `image_source_map` (
          `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
          `source_table` varchar(64) NOT NULL,
          `source_id` varchar(64) NOT NULL,
          `image_info_id` bigint(20) UNSIGNED NOT NULL,
          `migrated_at` datetime NOT NULL,
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_source`(`source_table`, `source_id`),
          KEY `idx_image_info`(`image_info_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='旧表与路径表映射'
        """,
        """
        CREATE TABLE IF NOT EXISTS `external_db_connection` (
          `id` int(10) UNSIGNED NOT NULL AUTO_INCREMENT,
          `name` varchar(100) NOT NULL DEFAULT '' COMMENT '连接名称',
          `host` varchar(255) NOT NULL DEFAULT '',
          `port` int(10) UNSIGNED NOT NULL DEFAULT 3306,
          `db_name` varchar(64) NOT NULL DEFAULT '',
          `username` varchar(100) NOT NULL DEFAULT '',
          `password_encrypted` text NOT NULL COMMENT '加密存储的密码',
          `charset` varchar(16) NOT NULL DEFAULT 'utf8',
          `remark` varchar(500) NOT NULL DEFAULT '',
          `enabled` tinyint(4) NOT NULL DEFAULT 1,
          `last_test_at` datetime NULL DEFAULT NULL,
          `last_test_ok` tinyint(4) NOT NULL DEFAULT 0,
          `last_test_message` varchar(500) NOT NULL DEFAULT '',
          `create_time` datetime NULL DEFAULT NULL,
          `update_time` datetime NULL DEFAULT NULL,
          PRIMARY KEY (`id`),
          KEY `idx_enabled`(`enabled`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='Web 配置的外部 MySQL 连接'
        """,
        """
        CREATE TABLE IF NOT EXISTS `blob_table_view` (
          `id` int(10) UNSIGNED NOT NULL AUTO_INCREMENT,
          `name` varchar(100) NOT NULL DEFAULT '' COMMENT '视图名称',
          `db_alias` varchar(32) NOT NULL DEFAULT 'default' COMMENT 'Django 数据库别名',
          `source_table` varchar(64) NOT NULL COMMENT '远程源表',
          `source_pk_column` varchar(64) NOT NULL DEFAULT 'id',
          `blob_column` varchar(64) NOT NULL COMMENT '被路径替代的 BLOB 列',
          `display_columns` text NOT NULL COMMENT 'JSON 列名数组，空则自动',
          `where_clause` varchar(500) NOT NULL DEFAULT '',
          `remark` varchar(500) NOT NULL DEFAULT '',
          `last_viewed_at` datetime NULL DEFAULT NULL,
          `create_time` datetime NULL DEFAULT NULL,
          `update_time` datetime NULL DEFAULT NULL,
          PRIMARY KEY (`id`),
          KEY `idx_db_table`(`db_alias`, `source_table`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='远程 BLOB 表虚拟视图配置'
        """,
        """
        CREATE TABLE IF NOT EXISTS `blob_migration_job` (
          `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
          `source_id` int(10) UNSIGNED NOT NULL,
          `status` varchar(20) NOT NULL DEFAULT 'pending',
          `dry_run` tinyint(4) NOT NULL DEFAULT 0,
          `skip_existing` tinyint(4) NOT NULL DEFAULT 1,
          `run_all` tinyint(4) NOT NULL DEFAULT 1,
          `retry_failed_only` tinyint(4) NOT NULL DEFAULT 0,
          `parent_job_id` bigint(20) UNSIGNED NULL DEFAULT NULL,
          `batch_size` int(10) UNSIGNED NOT NULL DEFAULT 50,
          `warm_thumbs_after` tinyint(4) NOT NULL DEFAULT 0,
          `cancel_requested` tinyint(4) NOT NULL DEFAULT 0,
          `total_estimate` int(10) UNSIGNED NOT NULL DEFAULT 0,
          `processed` int(10) UNSIGNED NOT NULL DEFAULT 0,
          `succeeded` int(10) UNSIGNED NOT NULL DEFAULT 0,
          `failed` int(10) UNSIGNED NOT NULL DEFAULT 0,
          `skipped` int(10) UNSIGNED NOT NULL DEFAULT 0,
          `last_pk_cursor` varchar(128) NOT NULL DEFAULT '',
          `message` varchar(500) NOT NULL DEFAULT '',
          `created_by` varchar(100) NOT NULL DEFAULT '',
          `started_at` datetime NULL DEFAULT NULL,
          `finished_at` datetime NULL DEFAULT NULL,
          `updated_at` datetime NULL DEFAULT NULL,
          `create_time` datetime NULL DEFAULT NULL,
          PRIMARY KEY (`id`),
          KEY `idx_source_status`(`source_id`, `status`),
          KEY `idx_status`(`status`),
          KEY `idx_create_time`(`create_time`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='BLOB 迁移后台任务'
        """,
        """
        CREATE TABLE IF NOT EXISTS `blob_migration_job_error` (
          `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
          `job_id` bigint(20) UNSIGNED NOT NULL,
          `source_pk` varchar(128) NOT NULL DEFAULT '',
          `filename` varchar(255) NOT NULL DEFAULT '',
          `error_message` varchar(1000) NOT NULL DEFAULT '',
          `retried` tinyint(4) NOT NULL DEFAULT 0,
          `create_time` datetime NULL DEFAULT NULL,
          PRIMARY KEY (`id`),
          KEY `idx_job`(`job_id`),
          KEY `idx_job_retried`(`job_id`, `retried`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='BLOB 迁移失败明细'
        """,
    ]

    try:
        with connection.cursor() as cursor:
            for ddl in ddl_statements:
                cursor.execute(ddl)
    except Exception:
        logger.warning("ensure migration tables failed", exc_info=True)
    ensure_blob_pr1_schema()


def _mysql_column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        [table, column],
    )
    return bool(cursor.fetchone()[0])


def _mysql_index_exists(cursor, table: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        """,
        [table, index_name],
    )
    return bool(cursor.fetchone()[0])


def ensure_blob_pr1_schema() -> None:
    """PR1 columns: source_column, blob_columns, object metadata for browse/migrate."""
    from django.db import connection

    if connection.vendor != "mysql":
        return

    alters = [
        ("image_source_map", "source_column", "varchar(64) NOT NULL DEFAULT '' COMMENT 'BLOB 列名' AFTER `source_id`"),
        ("blob_migration_source", "blob_columns", "text NOT NULL COMMENT 'JSON BLOB 列数组' AFTER `blob_column`"),
        ("blob_migration_source", "source_object_type", "varchar(20) NOT NULL DEFAULT 'table' AFTER `blob_columns`"),
        ("blob_migration_source", "path_lookup_table", "varchar(64) NOT NULL DEFAULT '' AFTER `source_object_type`"),
        ("blob_table_view", "database_name", "varchar(64) NOT NULL DEFAULT '' AFTER `db_alias`"),
        ("blob_table_view", "blob_columns", "text NOT NULL COMMENT 'JSON BLOB 列数组' AFTER `blob_column`"),
        ("blob_table_view", "source_object_type", "varchar(20) NOT NULL DEFAULT 'table' AFTER `source_table`"),
        ("blob_table_view", "path_lookup_table", "varchar(64) NOT NULL DEFAULT '' AFTER `source_object_type`"),
    ]

    try:
        with connection.cursor() as cursor:
            for table, column, ddl in alters:
                if not _mysql_column_exists(cursor, table, column):
                    cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}")
                    logger.info("added %s.%s", table, column)

            if _mysql_index_exists(cursor, "image_source_map", "uk_source"):
                cursor.execute("ALTER TABLE `image_source_map` DROP INDEX `uk_source`")
            if not _mysql_index_exists(cursor, "image_source_map", "uk_source"):
                cursor.execute(
                    "ALTER TABLE `image_source_map` ADD UNIQUE KEY `uk_source` (`source_table`, `source_id`, `source_column`)"
                )

            cursor.execute(
                """
                UPDATE `blob_migration_source`
                SET `blob_columns` = JSON_ARRAY(`blob_column`)
                WHERE (`blob_columns` IS NULL OR `blob_columns` = '')
                  AND `blob_column` <> ''
                """
            )
            cursor.execute(
                """
                UPDATE `blob_table_view`
                SET `blob_columns` = JSON_ARRAY(`blob_column`)
                WHERE (`blob_columns` IS NULL OR `blob_columns` = '')
                  AND `blob_column` <> ''
                """
            )
            cursor.execute(
                """
                UPDATE `image_source_map` m
                INNER JOIN (
                    SELECT source_table, MIN(blob_column) AS blob_column
                    FROM blob_migration_source
                    GROUP BY source_table
                ) s ON s.source_table = m.source_table
                SET m.source_column = s.blob_column
                WHERE m.source_column = ''
                """
            )
            cursor.execute(
                """
                UPDATE `blob_table_view` v
                INNER JOIN `external_db_connection` c
                    ON v.db_alias = CONCAT('external_', c.id)
                SET v.database_name = c.db_name
                WHERE v.database_name = ''
                """
            )
    except Exception:
        logger.warning("ensure blob pr1 schema failed", exc_info=True)
