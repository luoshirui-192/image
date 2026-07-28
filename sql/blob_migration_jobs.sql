/*
  BLOB 迁移后台任务表（全量迁移、进度、失败重试）

  用法:
    mysql -hHOST -uUSER -p DATABASE < sql/blob_migration_jobs.sql
*/

SET NAMES utf8;
SET FOREIGN_KEY_CHECKS = 0;

CREATE TABLE IF NOT EXISTS `blob_migration_job` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `source_id` int(10) UNSIGNED NOT NULL COMMENT 'blob_migration_source.id',
  `status` varchar(20) NOT NULL DEFAULT 'pending' COMMENT 'pending|running|completed|failed|cancelled',
  `dry_run` tinyint(4) NOT NULL DEFAULT 0,
  `skip_existing` tinyint(4) NOT NULL DEFAULT 1,
  `run_all` tinyint(4) NOT NULL DEFAULT 1 COMMENT '1=循环至无待迁',
  `retry_failed_only` tinyint(4) NOT NULL DEFAULT 0,
  `parent_job_id` bigint(20) UNSIGNED NULL DEFAULT NULL COMMENT '重试失败时来源任务',
  `batch_size` int(10) UNSIGNED NOT NULL DEFAULT 50,
  `warm_thumbs_after` tinyint(4) NOT NULL DEFAULT 0,
  `cancel_requested` tinyint(4) NOT NULL DEFAULT 0,
  `total_estimate` int(10) UNSIGNED NOT NULL DEFAULT 0,
  `processed` int(10) UNSIGNED NOT NULL DEFAULT 0,
  `succeeded` int(10) UNSIGNED NOT NULL DEFAULT 0,
  `failed` int(10) UNSIGNED NOT NULL DEFAULT 0,
  `skipped` int(10) UNSIGNED NOT NULL DEFAULT 0,
  `last_pk_cursor` varchar(128) NOT NULL DEFAULT '' COMMENT '游标分页最后主键',
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='BLOB 迁移后台任务';

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='BLOB 迁移失败明细';

SET FOREIGN_KEY_CHECKS = 1;
