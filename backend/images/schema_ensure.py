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
          `database_name` varchar(64) NOT NULL DEFAULT '',
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
          `source_column` varchar(64) NOT NULL DEFAULT '' COMMENT 'BLOB 列名',
          `image_info_id` bigint(20) UNSIGNED NOT NULL,
          `migrated_at` datetime NOT NULL,
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_source`(`source_table`, `source_id`, `source_column`),
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
          `pause_requested` tinyint(4) NOT NULL DEFAULT 0,
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


def _mysql_index_columns(cursor, table: str, index_name: str) -> list[str] | None:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        ORDER BY SEQ_IN_INDEX
        """,
        [table, index_name],
    )
    rows = cursor.fetchall()
    if not rows:
        return None
    return [row[0] for row in rows]


def _ensure_image_source_map_unique_index(cursor) -> None:
    """Upgrade uk_source to (source_table, source_id, source_column) idempotently."""
    desired = ["source_table", "source_id", "source_column"]
    current = _mysql_index_columns(cursor, "image_source_map", "uk_source")
    if current == desired:
        return
    if current is not None:
        cursor.execute("ALTER TABLE `image_source_map` DROP INDEX `uk_source`")
    cursor.execute(
        "ALTER TABLE `image_source_map` ADD UNIQUE KEY `uk_source` "
        "(`source_table`, `source_id`, `source_column`)"
    )
    logger.info("ensured image_source_map.uk_source columns=%s", desired)


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
        (
            "blob_migration_source",
            "blob_column_path_mappings",
            "text NOT NULL COMMENT 'JSON 每 BLOB 列路径映射' AFTER `path_lookup_table`",
        ),
        ("blob_migration_source", "database_name", "varchar(64) NOT NULL DEFAULT '' AFTER `db_alias`"),
        ("blob_table_view", "database_name", "varchar(64) NOT NULL DEFAULT '' AFTER `db_alias`"),
        ("blob_table_view", "blob_columns", "text NOT NULL COMMENT 'JSON BLOB 列数组' AFTER `blob_column`"),
        ("blob_table_view", "source_object_type", "varchar(20) NOT NULL DEFAULT 'table' AFTER `source_table`"),
        ("blob_table_view", "path_lookup_table", "varchar(64) NOT NULL DEFAULT '' AFTER `source_object_type`"),
        (
            "blob_table_view",
            "blob_column_path_mappings",
            "text NOT NULL COMMENT 'JSON 每 BLOB 列路径映射' AFTER `path_lookup_table`",
        ),
    ]

    try:
        with connection.cursor() as cursor:
            if not _mysql_column_exists(cursor, "image_source_map", "source_column"):
                cursor.execute(
                    "ALTER TABLE `image_source_map` "
                    "ADD COLUMN `source_column` varchar(64) NOT NULL DEFAULT '' "
                    "COMMENT 'BLOB 列名' AFTER `source_id`"
                )
                logger.info("added image_source_map.source_column")

            _ensure_image_source_map_unique_index(cursor)

            alters_without_source_column = [
                item for item in alters if item[0:2] != ("image_source_map", "source_column")
            ]
            for table, column, ddl in alters_without_source_column:
                if not _mysql_column_exists(cursor, table, column):
                    cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}")
                    logger.info("added %s.%s", table, column)

            if not _mysql_column_exists(cursor, "blob_migration_job_error", "source_column"):
                cursor.execute(
                    "ALTER TABLE `blob_migration_job_error` "
                    "ADD COLUMN `source_column` varchar(64) NOT NULL DEFAULT '' "
                    "COMMENT 'BLOB 列名' AFTER `source_pk`"
                )

            if not _mysql_column_exists(cursor, "blob_migration_job", "pause_requested"):
                cursor.execute(
                    "ALTER TABLE `blob_migration_job` "
                    "ADD COLUMN `pause_requested` tinyint(4) NOT NULL DEFAULT 0 "
                    "COMMENT '1=请求暂停' AFTER `cancel_requested`"
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
            cursor.execute(
                """
                UPDATE `blob_migration_source` s
                INNER JOIN `blob_table_view` v
                    ON s.db_alias = v.db_alias
                   AND s.source_table = v.source_table
                SET s.database_name = v.database_name
                WHERE s.database_name = ''
                  AND v.database_name <> ''
                """
            )
            cursor.execute(
                """
                UPDATE `blob_migration_source` s
                INNER JOIN `external_db_connection` c
                    ON s.db_alias = CONCAT('external_', c.id)
                SET s.database_name = c.db_name
                WHERE s.database_name = ''
                """
            )
    except Exception:
        logger.warning("ensure blob pr1 schema failed", exc_info=True)
    ensure_blob_sync_schema()


def ensure_blob_sync_schema() -> None:
    """BLOB sync fingerprint columns + blob_sync_run table."""
    from django.db import connection

    if connection.vendor != "mysql":
        return

    map_alters = [
        ("source_content_hash", "varchar(64) NOT NULL DEFAULT '' COMMENT '外部BLOB SHA256' AFTER `migrated_at`"),
        ("source_blob_length", "bigint(20) UNSIGNED NOT NULL DEFAULT 0 COMMENT '外部BLOB字节数' AFTER `source_content_hash`"),
        ("last_checked_at", "datetime NULL DEFAULT NULL COMMENT '上次检测时间' AFTER `source_blob_length`"),
        (
            "sync_status",
            "varchar(20) NOT NULL DEFAULT 'unknown' "
            "COMMENT 'unknown|in_sync|changed|missing|error|pending_resync' AFTER `last_checked_at`",
        ),
        ("last_sync_error", "varchar(500) NOT NULL DEFAULT '' AFTER `sync_status`"),
    ]
    source_alters = [
        ("auto_sync_enabled", "tinyint(4) NOT NULL DEFAULT 1 AFTER `last_run_at`"),
        ("sync_interval_minutes", "int(10) UNSIGNED NOT NULL DEFAULT 60 AFTER `auto_sync_enabled`"),
        ("sync_batch_size", "int(10) UNSIGNED NOT NULL DEFAULT 200 AFTER `sync_interval_minutes`"),
        ("sync_last_run_at", "datetime NULL DEFAULT NULL AFTER `sync_batch_size`"),
        ("sync_last_checked_map_id", "bigint(20) UNSIGNED NOT NULL DEFAULT 0 AFTER `sync_last_run_at`"),
        ("change_track_column", "varchar(64) NOT NULL DEFAULT '' AFTER `sync_last_checked_map_id`"),
        ("change_track_mode", "varchar(20) NOT NULL DEFAULT 'hash' AFTER `change_track_column`"),
    ]

    try:
        with connection.cursor() as cursor:
            for column, ddl in map_alters:
                if not _mysql_column_exists(cursor, "image_source_map", column):
                    cursor.execute(f"ALTER TABLE `image_source_map` ADD COLUMN `{column}` {ddl}")
                    logger.info("added image_source_map.%s", column)

            for column, ddl in source_alters:
                if not _mysql_column_exists(cursor, "blob_migration_source", column):
                    cursor.execute(f"ALTER TABLE `blob_migration_source` ADD COLUMN `{column}` {ddl}")
                    logger.info("added blob_migration_source.%s", column)

            cursor.execute(
                "UPDATE `blob_migration_source` SET `auto_sync_enabled` = 1 WHERE `auto_sync_enabled` = 0"
            )

            if not _mysql_index_exists(cursor, "image_source_map", "idx_sync_status"):
                cursor.execute(
                    "ALTER TABLE `image_source_map` ADD KEY `idx_sync_status` (`sync_status`, `last_checked_at`)"
                )
            if not _mysql_index_exists(cursor, "image_source_map", "idx_source_table_status"):
                cursor.execute(
                    "ALTER TABLE `image_source_map` ADD KEY `idx_source_table_status` "
                    "(`source_table`, `sync_status`)"
                )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS `blob_sync_run` (
                  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
                  `source_id` int(10) UNSIGNED NULL DEFAULT NULL,
                  `run_type` varchar(20) NOT NULL DEFAULT 'detect',
                  `status` varchar(20) NOT NULL DEFAULT 'running',
                  `checked` int(10) UNSIGNED NOT NULL DEFAULT 0,
                  `changed` int(10) UNSIGNED NOT NULL DEFAULT 0,
                  `resynced` int(10) UNSIGNED NOT NULL DEFAULT 0,
                  `failed` int(10) UNSIGNED NOT NULL DEFAULT 0,
                  `message` varchar(500) NOT NULL DEFAULT '',
                  `started_at` datetime NOT NULL,
                  `finished_at` datetime NULL DEFAULT NULL,
                  PRIMARY KEY (`id`),
                  KEY `idx_source_time` (`source_id`, `started_at`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='BLOB 同步运行记录'
                """
            )
    except Exception:
        logger.warning("ensure blob sync schema failed", exc_info=True)
    ensure_blob_source_uid_schema()


def ensure_blob_source_uid_schema() -> None:
    """Logical source_uid on migration/browse/map tables."""
    from django.db import connection

    if connection.vendor != "mysql":
        return

    alters = [
        ("blob_migration_source", "source_uid", "varchar(36) NOT NULL DEFAULT '' COMMENT '逻辑源 UUID' AFTER `change_track_mode`"),
        ("blob_table_view", "source_uid", "varchar(36) NOT NULL DEFAULT '' COMMENT '逻辑源 UUID' AFTER `database_name`"),
        ("image_source_map", "source_uid", "varchar(36) NOT NULL DEFAULT '' COMMENT '逻辑源 UUID' AFTER `source_column`"),
        (
            "image_source_map",
            "migration_source_id",
            "int(10) UNSIGNED NULL DEFAULT NULL COMMENT 'blob_migration_source.id' AFTER `source_uid`",
        ),
    ]

    try:
        with connection.cursor() as cursor:
            for table, column, ddl in alters:
                if not _mysql_column_exists(cursor, table, column):
                    cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}")
                    logger.info("added %s.%s", table, column)

            if not _mysql_index_exists(cursor, "image_source_map", "idx_map_source_uid"):
                cursor.execute(
                    "ALTER TABLE `image_source_map` ADD KEY `idx_map_source_uid` "
                    "(`source_uid`, `source_id`, `source_column`)"
                )
            if not _mysql_index_exists(cursor, "blob_migration_source", "idx_source_uid"):
                cursor.execute(
                    "ALTER TABLE `blob_migration_source` ADD KEY `idx_source_uid` (`source_uid`)"
                )
            if not _mysql_index_exists(cursor, "blob_table_view", "idx_view_source_uid"):
                cursor.execute(
                    "ALTER TABLE `blob_table_view` ADD KEY `idx_view_source_uid` (`source_uid`)"
                )
    except Exception:
        logger.warning("ensure blob source_uid schema failed", exc_info=True)
