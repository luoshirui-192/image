/*
 步骤 7：基础测试数据脚本
 用法：
   mysql -h192.168.1.154 -P3306 -u用户名 -p image_db < sql/seed_test_data.sql

 默认账号（Django pbkdf2_sha256，可用 scripts/generate_password_hash.py 重新生成）：
   admin / admin123  （管理员，可执行 SQL）
   testuser / user123 （普通用户，不可执行 SQL）

 测试图片路径为占位路径，需在后端 upload 目录放置对应文件或重新上传
*/

SET NAMES utf8;
USE `image_db`;

-- ----------------------------
-- 1. 系统用户
-- ----------------------------
DELETE FROM `sys_user` WHERE `username` IN ('admin', 'testuser');

INSERT INTO `sys_user` (`id`, `username`, `password`, `role`, `status`, `create_time`) VALUES
(1, 'admin', 'pbkdf2_sha256$600000$seedadmin001$8vQ+YnyoVHHtK/Ti3wyicQNRdQLmQpNGYlgMa0WX6qc=', 'admin', 1, NOW()),
(2, 'testuser', 'pbkdf2_sha256$600000$seeduser001$U5TeQcvaxUDCpPi9NXRor9y7/++wbC9elYKneOWT41Y=', 'user', 1, NOW());

-- ----------------------------
-- 2. 图片分类（幂等：不存在则插入）
-- ----------------------------
INSERT IGNORE INTO `image_category` (`id`, `category_name`, `sort`, `create_time`) VALUES
(1, '默认分类', 0, '2026-06-30 11:11:38'),
(2, '测试分类', 1, '2026-06-30 11:11:38'),
(3, '产品图', 2, NOW()),
(4, '风景图', 3, NOW());

-- ----------------------------
-- 3. 测试图片元数据（占位路径，不含真实文件）
-- ----------------------------
DELETE FROM `image_info` WHERE `id` BETWEEN 1 AND 5;

INSERT INTO `image_info` (
  `id`, `image_name`, `image_path`, `image_width`, `image_height`,
  `file_size`, `file_suffix`, `upload_time`, `update_time`,
  `upload_user`, `is_delete`, `category_id`, `tags`
) VALUES
(1, 'sample_landscape.jpg', 'upload/20260630/2/550e8400-e29b-41d4-a716-446655440001.jpg', 1920, 1080, 245760, 'jpg', '2026-06-30 10:00:00', '2026-06-30 10:00:00', 'admin', 0, 2, '风景,测试'),
(2, 'sample_product.png', 'upload/20260630/3/550e8400-e29b-41d4-a716-446655440002.png', 800, 600, 153600, 'png', '2026-06-30 11:30:00', '2026-06-30 11:30:00', 'admin', 0, 3, '产品,白底'),
(3, 'sample_avatar.webp', 'upload/20260630/1/550e8400-e29b-41d4-a716-446655440003.webp', 256, 256, 12288, 'webp', '2026-06-30 12:00:00', '2026-06-30 12:00:00', 'testuser', 0, 1, '头像'),
(4, 'deleted_sample.gif', 'upload/20260629/2/550e8400-e29b-41d4-a716-446655440004.gif', 640, 480, 98304, 'gif', '2026-06-29 09:00:00', '2026-06-29 15:00:00', 'testuser', 1, 2, '已删除示例'),
(5, 'sample_banner.jpg', 'upload/20260630/4/550e8400-e29b-41d4-a716-446655440005.jpg', 1280, 720, 307200, 'jpg', '2026-06-30 14:00:00', '2026-06-30 14:00:00', 'admin', 0, 4, '横幅,风景');

-- ----------------------------
-- 4. 操作日志样例
-- ----------------------------
DELETE FROM `operate_log` WHERE `id` BETWEEN 1 AND 4;

INSERT INTO `operate_log` (`id`, `user_id`, `username`, `action_type`, `sql_content`, `detail`, `ip`, `create_time`) VALUES
(1, 1, 'admin', 'login', NULL, '管理员登录成功', '127.0.0.1', '2026-06-30 09:00:00'),
(2, 1, 'admin', 'upload', NULL, '上传图片 sample_landscape.jpg', '127.0.0.1', '2026-06-30 10:00:00'),
(3, 1, 'admin', 'sql_query', 'SELECT id, image_name, image_path FROM image_info WHERE is_delete = 0 LIMIT 10', 'SQL 查询返回 3 行', '127.0.0.1', '2026-06-30 10:05:00'),
(4, 2, 'testuser', 'delete', NULL, '逻辑删除图片 deleted_sample.gif (id=4)', '192.168.1.100', '2026-06-29 15:00:00');

-- 重置自增起点，避免与测试 ID 冲突
ALTER TABLE `sys_user` AUTO_INCREMENT = 10;
ALTER TABLE `image_info` AUTO_INCREMENT = 100;
ALTER TABLE `operate_log` AUTO_INCREMENT = 100;
ALTER TABLE `image_category` AUTO_INCREMENT = 10;
