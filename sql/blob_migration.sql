/*
  BLOB 迁移与源表映射（接入外部库时使用）

  用法（在目标 MySQL 库执行）:
    mysql -hHOST -uUSER -p DATABASE < sql/blob_migration.sql

  或在已有 image_db.sql 之外单独执行本脚本。
*/

SET NAMES utf8;
SET FOREIGN_KEY_CHECKS = 0;

-- 迁移任务配置：描述从哪张旧表读 BLOB
CREATE TABLE IF NOT EXISTS `blob_migration_source` (
  `id` int(10) UNSIGNED NOT NULL AUTO_INCREMENT,
  `name` varchar(100) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '' COMMENT '任务名称',
  `source_table` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL COMMENT '源表名',
  `source_pk_column` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT 'id' COMMENT '源表主键列',
  `blob_column` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL COMMENT 'BLOB 列名',
  `blob_columns` text CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL COMMENT 'JSON BLOB 列数组',
  `source_object_type` varchar(20) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT 'table',
  `path_lookup_table` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '',
  `name_column` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '' COMMENT '文件名列（可选）',
  `suffix_column` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '' COMMENT '后缀列（可选）',
  `category_id` int(10) UNSIGNED NOT NULL COMMENT '写入 image_info 的分类',
  `upload_user` varchar(100) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT 'migration' COMMENT '入库 upload_user',
  `tags` varchar(500) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '',
  `where_clause` varchar(500) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '' COMMENT '额外 WHERE（不含 WHERE 关键字）',
  `db_alias` varchar(32) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT 'default' COMMENT 'Django 数据库别名 default|legacy',
  `enabled` tinyint(4) NOT NULL DEFAULT 1,
  `last_run_at` datetime NULL DEFAULT NULL,
  `create_time` datetime NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_enabled`(`enabled`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8 COLLATE = utf8_general_ci COMMENT = 'BLOB 迁移源配置' ROW_FORMAT = COMPACT;

-- 旧表主键 → image_info 映射（原表结构不改）
CREATE TABLE IF NOT EXISTS `image_source_map` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `source_table` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL,
  `source_id` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL COMMENT '源表主键字符串',
  `source_column` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '' COMMENT 'BLOB 列名',
  `image_info_id` bigint(20) UNSIGNED NOT NULL,
  `migrated_at` datetime NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_source`(`source_table`, `source_id`, `source_column`) USING BTREE,
  KEY `idx_image_info`(`image_info_id`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8 COLLATE = utf8_general_ci COMMENT = '旧表与路径表映射' ROW_FORMAT = COMPACT;

SET FOREIGN_KEY_CHECKS = 1;

-- Web 配置的外部 MySQL 连接（密码加密存储于 password_encrypted）
CREATE TABLE IF NOT EXISTS `external_db_connection` (
  `id` int(10) UNSIGNED NOT NULL AUTO_INCREMENT,
  `name` varchar(100) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '' COMMENT '连接名称',
  `host` varchar(255) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '',
  `port` int(10) UNSIGNED NOT NULL DEFAULT 3306,
  `db_name` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '',
  `username` varchar(100) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '',
  `password_encrypted` text CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL COMMENT '加密存储的密码',
  `charset` varchar(16) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT 'utf8',
  `remark` varchar(500) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '',
  `enabled` tinyint(4) NOT NULL DEFAULT 1,
  `last_test_at` datetime NULL DEFAULT NULL,
  `last_test_ok` tinyint(4) NOT NULL DEFAULT 0,
  `last_test_message` varchar(500) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '',
  `create_time` datetime NULL DEFAULT NULL,
  `update_time` datetime NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_enabled`(`enabled`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8 COLLATE = utf8_general_ci COMMENT = 'Web 配置的外部 MySQL 连接' ROW_FORMAT = COMPACT;

-- 远程 BLOB 表虚拟视图（不建物理表，仅保存查询配置）
CREATE TABLE IF NOT EXISTS `blob_table_view` (
  `id` int(10) UNSIGNED NOT NULL AUTO_INCREMENT,
  `name` varchar(100) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '' COMMENT '浏览配置名称',
  `db_alias` varchar(32) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT 'default' COMMENT 'Django 数据库别名',
  `database_name` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '' COMMENT '浏览所在库名',
  `source_table` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL COMMENT '远程源表或数据库视图',
  `source_object_type` varchar(20) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT 'table',
  `path_lookup_table` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '',
  `source_pk_column` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT 'id',
  `blob_column` varchar(64) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL COMMENT '主 BLOB 列（兼容）',
  `blob_columns` text CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL COMMENT 'JSON BLOB 列数组',
  `display_columns` text CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL COMMENT 'JSON 列名数组，空则自动',
  `where_clause` varchar(500) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '',
  `remark` varchar(500) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL DEFAULT '',
  `last_viewed_at` datetime NULL DEFAULT NULL,
  `create_time` datetime NULL DEFAULT NULL,
  `update_time` datetime NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_db_table`(`db_alias`, `source_table`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8 COLLATE = utf8_general_ci COMMENT = '远程 BLOB 表虚拟视图配置' ROW_FORMAT = COMPACT;

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
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_source_status`(`source_id`, `status`) USING BTREE,
  KEY `idx_status`(`status`) USING BTREE,
  KEY `idx_create_time`(`create_time`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8 COLLATE = utf8_general_ci COMMENT = 'BLOB 迁移后台任务' ROW_FORMAT = COMPACT;

CREATE TABLE IF NOT EXISTS `blob_migration_job_error` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `job_id` bigint(20) UNSIGNED NOT NULL,
  `source_pk` varchar(128) NOT NULL DEFAULT '',
  `filename` varchar(255) NOT NULL DEFAULT '',
  `error_message` varchar(1000) NOT NULL DEFAULT '',
  `retried` tinyint(4) NOT NULL DEFAULT 0,
  `create_time` datetime NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_job`(`job_id`) USING BTREE,
  KEY `idx_job_retried`(`job_id`, `retried`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8 COLLATE = utf8_general_ci COMMENT = 'BLOB 迁移失败明细' ROW_FORMAT = COMPACT;

SET FOREIGN_KEY_CHECKS = 1;
