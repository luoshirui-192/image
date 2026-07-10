# 第 10 章：脚本、SQL、Docker 与 deploy

---

## `sql/` 目录

| 文件 | 作用 | 阅读要点 |
|------|------|----------|
| `image_db.sql` | 原始业务表 DDL | `image_info`、`image_category`、`sys_user` |
| `blob_migration.sql` | 迁移相关表 | `blob_migration_source`、`image_source_map` |
| `blob_migration_jobs.sql` | 任务表 | `blob_migration_job`、error 表 |
| `seed_test_data.sql` | 测试账号/样例 | admin 密码 hash |
| `optimize_indexes.sql` | 索引与触发器 | 列表性能 |
| `README.md` | 执行顺序 | init 脚本引用关系 |

**Docker 初始化：** `docker/mysql-init/00-init-app.sh` 在首次启动 MySQL 时导入上述 SQL。

---

## `scripts/` 常用脚本

| 脚本 | 逐行意图（概要） |
|------|------------------|
| `smoke_test.py` | 登录→categories→images→config 一串 GET 冒烟 |
| `backup_mysql.py` | mysqldump 到 backups/mysql |
| `backup_upload.py` | 打包 upload 或 MinIO 同步 |
| `backup_all.py` | 编排 mysql+upload |
| `restore_mysql.py` | 从 dump 恢复 |
| `init_storage.py` | 创建 MinIO bucket/prefix |
| `prepare_production.py` | 检查 env、SECRET_KEY、DEBUG |
| `verify_production.py` | 部署后验证 |
| `render_nginx_config.py` | 模板→`deploy/nginx/generated/` |
| `render_gunicorn_service.py` | systemd unit 生成 |
| `copy_mysql_table.py` | 跨实例拷表（运维） |
| `generate_secret_key.py` | 随机 Django SECRET_KEY |
| `test_file_security.py` | 上传安全单元测试 |

---

## `docker/` 文件

| 文件 | 说明 |
|------|------|
| `Dockerfile.backend` | Python 3.11、pip install、COPY backend、entrypoint |
| `Dockerfile.nginx` | 多阶段：Node build frontend → nginx alpine |
| `nginx/default.conf` | `/` 静态；`/api` proxy_pass backend:8000 |
| `backend-entrypoint.sh` | 等 DB、migrate、Gunicorn |
| `maintenance-loop.sh` | scheduler 循环 |
| `ensure_mysql57_triggers.py` | 老 MySQL 触发器补丁 |
| `mysql-init/*.sh` | 首次 DB 初始化 |

### `Dockerfile.nginx` 构建阶段（对照构建错误）

```dockerfile
# frontend-build 阶段
COPY frontend/
RUN cp .env.production.example .env.production && npm run build
# → 任何 .vue 模板语法错误在此暴露
```

---

## `deploy/` 非 Docker 部署

| 路径 | 说明 |
|------|------|
| `nginx/image_db.conf.template` | 反向代理 + 静态 root |
| `gunicorn/gunicorn.conf.py` | workers、bind unix socket |
| `gunicorn/image_db.service.template` | systemd |
| `backup/cron.example` | 定时 backup_all |
| `paths.env.example` | 渲染脚本变量 |

---

## `docs/` 现有文档

| 文件 | 与代码导读关系 |
|------|----------------|
| `deploy.md` | 部署步骤，配合第 1 章 |
| `storage.md` | 读 `utils/storage.py` 前先看 |
| `file_security.md` | 读 `file_security.py` 前先看 |
| `quickstart-docker.md` | 最快跑起来 |

---

## 建议的 7 天自学节奏

| 天 | 内容 |
|----|------|
| 1 | 第 0-1 章 + 跑通 Docker |
| 2 | 第 2 章 settings + utils |
| 3 | 第 3-4 章 认证 + 上传链路 |
| 4 | 第 5 章 迁移 + 浏览后端 |
| 5 | 第 7-8 章 前端框架 + 上传页 |
| 6 | 第 9 章 BlobMigrate + BlobTableViews |
| 7 | 第 6、10 章 运维脚本 + 测试 |

---

## 回到总索引

[README.md](./README.md)
