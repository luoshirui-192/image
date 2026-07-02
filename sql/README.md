# 数据库脚本说明

## 文件清单

| 文件 | 用途 |
|------|------|
| [image_db.sql](image_db.sql) | 全量建库脚本（原始表结构，请勿修改） |
| [optimize_indexes.sql](optimize_indexes.sql) | 增量索引优化 + update_time 触发器 |
| [seed_test_data.sql](seed_test_data.sql) | 种子数据（用户、分类、示例图片、日志） |
| [fix_django_migrate.sql](fix_django_migrate.sql) | migrate 失败 errno 150 时清理 Django 内置表 |

## 推荐执行顺序

### 全新安装

```bash
mysql -h192.168.1.154 -P3306 -u用户名 -p < image_db.sql
mysql -h192.168.1.154 -P3306 -u用户名 -p image_db < sql/optimize_indexes.sql
mysql -h192.168.1.154 -P3306 -u用户名 -p image_db < sql/seed_test_data.sql
```

### 已有库仅优化索引

```bash
mysql -h192.168.1.154 -P3306 -u用户名 -p image_db < sql/optimize_indexes.sql
```

## 测试账号

| 用户名 | 密码 | 角色 |
|--------|------|------|
| admin | admin123 | admin |
| testuser | user123 | user |

重新生成密码哈希：

```bash
python scripts/generate_password_hash.py admin123
python scripts/generate_password_hash.py user123
```

## migrate 失败 errno 150

业务表 `sys_user` 等为 **MyISAM**，Django 创建外键时会报错。后端已关闭外键创建。若 migrate 中断，执行：

```bash
mysql -h192.168.1.154 -P3306 -u用户名 -p image_db < sql/fix_django_migrate.sql
cd backend
python manage.py migrate
```

### UnicodeEncodeError: charmap（中文编码）

migrate 会为 `auth_permission` 写入中文权限名（来自 Model 的 `verbose_name`）。Windows 下若 MySQL 连接编码为 `cp1252` 会报错。项目已在 `config/db_backend/base.py` 将客户端编码强制为 `utf8`。更新代码后重新执行 `migrate` 即可。

## 索引优化说明

| 表 | 索引 | 适用查询 |
|----|------|----------|
| image_info | uk_image_path | 路径唯一、防重复入库 |
| image_info | idx_list_active (is_delete, upload_time) | 正常图片列表按时间排序 |
| image_info | idx_list_category (is_delete, category_id, upload_time) | 按分类筛选 |
| image_info | idx_upload_user | 按上传人筛选 |
| image_info | idx_image_name | 按文件名前缀搜索 |
| operate_log | idx_log_time_action | 日志按时间+类型 |
| operate_log | idx_log_username_time | 日志按用户+时间 |
| sys_user | idx_status_role | 查询启用中的管理员/用户 |
| image_category | uk_category_name | 分类名不重复 |
