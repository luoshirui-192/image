/*
 修复 migrate 失败 (errno 150) 后的 Django 内置表清理脚本

 原因：业务表 sys_user 等为 MyISAM，Django 默认会创建指向用户表的外键，导致失败。
 项目已在 config/db_backend 中关闭外键创建，执行本脚本后重新 migrate 即可。

 用法（会删除 Django 内置表，不影响 sys_user / image_info 等业务表）：
    mysql -h192.168.1.154 -P3306 -u用户名 -p image_db < sql/fix_django_migrate.sql
    cd backend && python manage.py migrate
*/

SET NAMES utf8;
USE `image_db`;

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `django_admin_log`;
DROP TABLE IF EXISTS `django_session`;
DROP TABLE IF EXISTS `auth_group_permissions`;
DROP TABLE IF EXISTS `auth_permission`;
DROP TABLE IF EXISTS `auth_group`;
DROP TABLE IF EXISTS `django_content_type`;
DROP TABLE IF EXISTS `django_migrations`;

SET FOREIGN_KEY_CHECKS = 1;
