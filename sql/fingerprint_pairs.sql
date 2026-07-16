-- Fingerprint pair comparison tables (MySQL)
-- Applied automatically via fingerprints.schema_ensure on MySQL startup.
-- For manual apply: mysql -u ... image_db < sql/fingerprint_pairs.sql

CREATE TABLE IF NOT EXISTS `fingerprint_layer_type` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `layer_key` varchar(64) NOT NULL,
  `label` varchar(100) NOT NULL DEFAULT '',
  `color` varchar(20) NOT NULL DEFAULT '#e53935',
  `suffixes` varchar(200) NOT NULL DEFAULT '',
  `default_algo_name` varchar(100) NOT NULL DEFAULT 'default',
  `default_setlen` int NOT NULL DEFAULT 0,
  `default_setang` int NOT NULL DEFAULT 256,
  `sort_order` int NOT NULL DEFAULT 0,
  `enabled` smallint NOT NULL DEFAULT 1,
  `create_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_fp_layer_key` (`layer_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='指纹特征层类型配置';

CREATE TABLE IF NOT EXISTS `fingerprint_pair` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `batch_name` varchar(200) NOT NULL DEFAULT '',
  `finger_position` varchar(40) NOT NULL DEFAULT '',
  `match_score` double DEFAULT NULL,
  `left_image_id` bigint unsigned NOT NULL DEFAULT 0,
  `right_image_id` bigint unsigned NOT NULL DEFAULT 0,
  `left_person_id` varchar(64) NOT NULL DEFAULT '',
  `right_person_id` varchar(64) NOT NULL DEFAULT '',
  `left_image_name` varchar(255) NOT NULL DEFAULT '',
  `right_image_name` varchar(255) NOT NULL DEFAULT '',
  `source_dir` varchar(500) NOT NULL DEFAULT '',
  `upload_user` varchar(100) NOT NULL DEFAULT '',
  `tags` varchar(500) NOT NULL DEFAULT '',
  `is_delete` smallint NOT NULL DEFAULT 0,
  `create_time` datetime DEFAULT NULL,
  `update_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_fp_pair_position` (`finger_position`),
  KEY `idx_fp_pair_score` (`match_score`),
  KEY `idx_fp_pair_batch` (`batch_name`),
  KEY `idx_fp_pair_active` (`is_delete`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='指纹成对样本';

CREATE TABLE IF NOT EXISTS `fingerprint_feature_layer` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `pair_id` bigint unsigned NOT NULL,
  `side` varchar(10) NOT NULL DEFAULT 'left',
  `layer_type` varchar(64) NOT NULL DEFAULT '',
  `algo_name` varchar(100) NOT NULL DEFAULT 'default',
  `algo_version` varchar(64) NOT NULL DEFAULT '1.0',
  `template_path` varchar(500) NOT NULL DEFAULT '',
  `file_suffix` varchar(40) NOT NULL DEFAULT '',
  `file_hash` varchar(64) NOT NULL DEFAULT '',
  `file_size` bigint unsigned NOT NULL DEFAULT 0,
  `setlen` int NOT NULL DEFAULT 0,
  `setang` int NOT NULL DEFAULT 256,
  `minutiae_count` int NOT NULL DEFAULT 0,
  `minutiae_json` mediumtext,
  `create_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_fp_layer_pair` (`pair_id`),
  KEY `idx_fp_layer_type` (`layer_type`),
  KEY `idx_fp_layer_version` (`algo_name`, `algo_version`),
  KEY `idx_fp_layer_side_type` (`pair_id`, `side`, `layer_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='指纹特征层（模板）';

CREATE TABLE IF NOT EXISTS `fingerprint_import_job` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `zip_path` varchar(500) NOT NULL DEFAULT '',
  `zip_name` varchar(255) NOT NULL DEFAULT '',
  `status` varchar(20) NOT NULL DEFAULT 'pending',
  `algo_version` varchar(64) NOT NULL DEFAULT '1.0',
  `tags` varchar(500) NOT NULL DEFAULT '',
  `skip_existing` smallint NOT NULL DEFAULT 1,
  `category_id` int unsigned DEFAULT NULL,
  `total_estimate` int unsigned NOT NULL DEFAULT 0,
  `processed` int unsigned NOT NULL DEFAULT 0,
  `succeeded` int unsigned NOT NULL DEFAULT 0,
  `failed` int unsigned NOT NULL DEFAULT 0,
  `skipped` int unsigned NOT NULL DEFAULT 0,
  `cancel_requested` smallint NOT NULL DEFAULT 0,
  `message` varchar(500) NOT NULL DEFAULT '',
  `last_error` varchar(500) NOT NULL DEFAULT '',
  `created_by` varchar(100) NOT NULL DEFAULT '',
  `create_time` datetime DEFAULT NULL,
  `started_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_fp_import_status` (`status`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='指纹 zip 后台导入任务';

INSERT IGNORE INTO `fingerprint_layer_type`
  (`layer_key`, `label`, `color`, `suffixes`, `default_algo_name`, `default_setlen`, `default_setang`, `sort_order`, `enabled`, `create_time`)
VALUES
  ('bidiso', 'Bidiso', '#e53935', 'bidiso', 'bidiso', 0, 256, 10, 1, NOW()),
  ('neuiso', 'neuiso', '#1e88e5', 'neuiso', 'neuiso', 0, 256, 20, 1, NOW());
