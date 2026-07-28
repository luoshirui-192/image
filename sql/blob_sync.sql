-- BLOB 外部源自动同步（指纹检测 + 重迁）
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

ALTER TABLE `image_source_map`
  ADD COLUMN IF NOT EXISTS `source_content_hash` varchar(64) NOT NULL DEFAULT '' COMMENT '外部BLOB SHA256' AFTER `migrated_at`,
  ADD COLUMN IF NOT EXISTS `source_blob_length` bigint(20) UNSIGNED NOT NULL DEFAULT 0 COMMENT '外部BLOB字节数' AFTER `source_content_hash`,
  ADD COLUMN IF NOT EXISTS `last_checked_at` datetime NULL DEFAULT NULL COMMENT '上次检测时间' AFTER `source_blob_length`,
  ADD COLUMN IF NOT EXISTS `sync_status` varchar(20) NOT NULL DEFAULT 'unknown' COMMENT 'unknown|in_sync|changed|missing|error|pending_resync' AFTER `last_checked_at`,
  ADD COLUMN IF NOT EXISTS `last_sync_error` varchar(500) NOT NULL DEFAULT '' AFTER `sync_status`;

-- MySQL 5.7 may not support IF NOT EXISTS on ADD COLUMN; schema_ensure handles idempotent alters.

ALTER TABLE `blob_migration_source`
  ADD COLUMN IF NOT EXISTS `auto_sync_enabled` tinyint(4) NOT NULL DEFAULT 1 AFTER `last_run_at`,
  ADD COLUMN IF NOT EXISTS `sync_interval_minutes` int(10) UNSIGNED NOT NULL DEFAULT 60 AFTER `auto_sync_enabled`,
  ADD COLUMN IF NOT EXISTS `sync_batch_size` int(10) UNSIGNED NOT NULL DEFAULT 200 AFTER `sync_interval_minutes`,
  ADD COLUMN IF NOT EXISTS `sync_last_run_at` datetime NULL DEFAULT NULL AFTER `sync_batch_size`,
  ADD COLUMN IF NOT EXISTS `sync_last_checked_map_id` bigint(20) UNSIGNED NOT NULL DEFAULT 0 AFTER `sync_last_run_at`,
  ADD COLUMN IF NOT EXISTS `change_track_column` varchar(64) NOT NULL DEFAULT '' AFTER `sync_last_checked_map_id`,
  ADD COLUMN IF NOT EXISTS `change_track_mode` varchar(20) NOT NULL DEFAULT 'hash' AFTER `change_track_column`;

CREATE TABLE IF NOT EXISTS `blob_sync_run` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `source_id` int(10) UNSIGNED NULL DEFAULT NULL COMMENT 'NULL=全局 backfill',
  `run_type` varchar(20) NOT NULL DEFAULT 'detect' COMMENT 'detect|resync|backfill',
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='BLOB 同步运行记录';

SET FOREIGN_KEY_CHECKS = 1;
