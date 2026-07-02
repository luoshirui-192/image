/*
 步骤 6：数据库索引优化脚本（增量执行）
 适用场景：已有 image_db 库，无需重建表，仅追加/调整索引与触发器

 用法：
   mysql -h192.168.1.154 -P3306 -u用户名 -p image_db < sql/optimize_indexes.sql

 注意：若索引已存在会报错，可忽略或先 DROP INDEX 再执行
*/

SET NAMES utf8;
USE `image_db`;

-- image_category：分类名唯一
ALTER TABLE `image_category`
  ADD UNIQUE INDEX `uk_category_name` (`category_name`);

-- image_info：移除低选择性单列索引，改为复合索引
ALTER TABLE `image_info`
  DROP INDEX `idx_is_delete`,
  DROP INDEX `idx_category_id`;

-- 原 idx_image_path 改为唯一索引 uk_image_path
ALTER TABLE `image_info`
  DROP INDEX `idx_image_path`;

ALTER TABLE `image_info`
  ADD UNIQUE INDEX `uk_image_path` (`image_path`(191)),
  ADD INDEX `idx_upload_user` (`upload_user`),
  ADD INDEX `idx_image_name` (`image_name`(100)),
  ADD INDEX `idx_list_active` (`is_delete`, `upload_time`),
  ADD INDEX `idx_list_category` (`is_delete`, `category_id`, `upload_time`);

-- operate_log：日志查询复合索引
ALTER TABLE `operate_log`
  ADD INDEX `idx_log_time_action` (`create_time`, `action_type`),
  ADD INDEX `idx_log_username_time` (`username`, `create_time`);

-- sys_user：启用状态 + 角色
ALTER TABLE `sys_user`
  ADD INDEX `idx_status_role` (`status`, `role`);

-- image_info：update_time 自动维护触发器
DROP TRIGGER IF EXISTS `trg_image_info_update_time`;
DELIMITER ;;
CREATE TRIGGER `trg_image_info_update_time` BEFORE UPDATE ON `image_info`
FOR EACH ROW
BEGIN
  SET NEW.update_time = CURRENT_TIMESTAMP;
END;;
DELIMITER ;

-- image_info：insert 时 upload_time / update_time 默认取 CURRENT_TIMESTAMP
DROP TRIGGER IF EXISTS `trg_image_info_insert_time`;
DELIMITER ;;
CREATE TRIGGER `trg_image_info_insert_time` BEFORE INSERT ON `image_info`
FOR EACH ROW
BEGIN
  IF NEW.upload_time IS NULL THEN
    SET NEW.upload_time = CURRENT_TIMESTAMP;
  END IF;
  IF NEW.update_time IS NULL THEN
    SET NEW.update_time = NEW.upload_time;
  END IF;
END;;
DELIMITER ;
