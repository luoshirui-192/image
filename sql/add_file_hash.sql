/*
 增量脚本：为 image_info 添加 file_hash 列，用于重复图片检测
 用法：mysql -u用户 -p image_db < sql/add_file_hash.sql
*/
SET NAMES utf8;
USE `image_db`;

SET @col_exists = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'image_info'
    AND COLUMN_NAME = 'file_hash'
);

SET @sql = IF(
  @col_exists = 0,
  'ALTER TABLE `image_info` ADD COLUMN `file_hash` varchar(64) NOT NULL DEFAULT '''' COMMENT ''文件内容 SHA256'' AFTER `file_suffix`',
  'SELECT ''file_hash column already exists'' AS info'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists = (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'image_info'
    AND INDEX_NAME = 'idx_file_hash'
);

SET @sql = IF(
  @idx_exists = 0,
  'ALTER TABLE `image_info` ADD INDEX `idx_file_hash` (`file_hash`)',
  'SELECT ''idx_file_hash already exists'' AS info'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
