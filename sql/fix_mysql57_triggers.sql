-- MySQL 5.7 严格模式：移除触发器中对 '0000-00-00' 的引用
SET NAMES utf8;
USE `image_db`;

DROP TRIGGER IF EXISTS `trg_image_info_update_time`;
DROP TRIGGER IF EXISTS `trg_image_info_insert_time`;

DELIMITER ;;
CREATE TRIGGER `trg_image_info_update_time` BEFORE UPDATE ON `image_info`
FOR EACH ROW
BEGIN
  SET NEW.update_time = CURRENT_TIMESTAMP;
END;;

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
