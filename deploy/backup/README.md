# 备份与恢复（步骤 30）

## 脚本

| 脚本 | 说明 |
|------|------|
| `scripts/backup_mysql.py` | `mysqldump` → `backups/mysql/image_db_*.sql.gz` |
| `scripts/backup_upload.py` | `upload/` → `backups/upload/upload_*.tar.gz` |
| `scripts/backup_all.py` | 上述两者一键执行 |
| `scripts/restore_mysql.py` | 从 `.sql.gz` 恢复数据库（需 `--yes`） |
| `scripts/smoke_test.py` | HTTP 冒烟测试 |

配置项见 `deploy/paths.env.example` 中 `BACKUP_ROOT`、`BACKUP_RETENTION_DAYS`。

## 手动备份

```bash
cd /opt/image_db
python3 scripts/backup_all.py

# 预览命令
python3 scripts/backup_all.py --dry-run
```

备份目录默认：`backups/mysql/`、`backups/upload/`（可通过 `deploy/paths.env` 的 `BACKUP_ROOT` 修改）。

## 定时任务

参考 `deploy/backup/cron.example`，将 `PROJECT_ROOT` 与 Python 路径改为服务器实际值。

## 冒烟测试

服务启动后：

```bash
# 直连 Gunicorn
python3 scripts/smoke_test.py --base-url http://127.0.0.1:8000

# 经 Nginx 全链路
python3 scripts/smoke_test.py --base-url http://192.168.1.100
```

默认使用 `admin / admin123`（种子数据账号）；生产环境请改为实际管理员账号。

检查项：health → login → me → categories → images → config → logs/stats。

## 恢复

```bash
python3 scripts/restore_mysql.py backups/mysql/image_db_YYYYMMDD_HHMMSS.sql.gz --dry-run
python3 scripts/restore_mysql.py backups/mysql/image_db_YYYYMMDD_HHMMSS.sql.gz --yes
```

`upload/` 备份为 tar.gz，解压到原 `UPLOAD_ROOT` 即可。

完整说明见 [docs/deploy.md](../../docs/deploy.md) 步骤 30。
