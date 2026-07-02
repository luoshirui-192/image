# 生产部署与运维

## 部署模型（必读）

| 环境 | 机器 | 用途 |
|------|------|------|
| **开发** | 当前这台电脑 | 写代码、`runserver`、`npm run dev`、跑测试 |
| **运行** | **另一台服务器** | 对外提供服务（Nginx + Gunicorn + MySQL + `upload/`） |

原则：

- 开发机 **不必** 长期保持 `DEBUG=False` 或生产 `.env`；日常用 `backend/.env`（开发配置）即可。
- 在开发机上构建、测试通过后，将 **同一套项目代码**（或打包产物）部署到服务器；在 **服务器上** 单独配置 `backend/.env`（生产项）。
- 服务器与开发机可以共用同一 MySQL（如 `192.168.1.154`），也可以服务器本机装库；`DB_HOST` 等在服务器 `.env` 里按实际填写。
- 步骤 27 的 `prepare_production.py` / `npm run build` 可在开发机执行，用于验证「能部署」；**生产密钥与 `ALLOWED_HOSTS` 在目标服务器上填写**，不要依赖开发机上的 `.env` 原样拷贝（除非两台机器角色相同）。

交付到服务器时通常包含：项目代码、`frontend/dist/`（或到服务器再 `npm run build`）、`sql/` 脚本；**不包含** `node_modules/`、开发用 `db.sqlite3`、本机测试数据。

---

## 步骤 27：生产环境准备（当前文档）

目标：确认项目具备可部署形态（生产配置模板、前端构建、就绪检查）；**生产 `.env` 在目标服务器上生效**。

在开发机上可先验证构建与 `verify_production.py`；正式对外服务在服务器完成步骤 27 清单 + 28（Nginx）+ 29（Gunicorn）。

### 前置条件

- Python 3.10+
- Node.js 18+（构建前端）
- 可访问的 MySQL（`image_db` 已建库，见 `sql/README.md`）

### 一键准备

```powershell
cd E:\图像路径式数据库管理系统

# 写入生产 env 模板（首次）
python scripts\prepare_production.py --write-env

# 编辑 backend\.env：SECRET_KEY、IMAGE_ACCESS_SECRET、DB_PASSWORD、ALLOWED_HOSTS、CORS
python scripts\generate_secret_key.py

# 安装依赖、migrate、构建前端
python scripts\prepare_production.py
```

### 手动步骤

```powershell
# 1. 存储目录
python scripts\init_storage.py

# 2. 后端配置
cd backend
copy .env.production.example .env
pip install -r requirements-production.txt
python manage.py migrate

# 3. 前端生产构建
cd ..\frontend
copy .env.production.example .env.production
npm install
npm run build
```

构建产物：`frontend/dist/`（供步骤 28 Nginx 托管）。

### 生产 `.env` 关键项

| 变量 | 说明 |
|------|------|
| `DEBUG=False` | 必须关闭 |
| `SECRET_KEY` | 随机字符串，勿用默认值 |
| `IMAGE_ACCESS_SECRET` | 图片访问令牌密钥，独立于 SECRET_KEY |
| `DB_ENGINE=mysql` | 生产不要用 sqlite |
| `ALLOWED_HOSTS` | 服务器 IP 或域名，逗号分隔 |
| `CORS_ALLOWED_ORIGINS` | 浏览器访问前端的 origin |

### 验收

```powershell
# 本地就绪检查（不启动服务）
python scripts\verify_production.py

# 启动 API 后 HTTP 检查
cd backend
python manage.py runserver 0.0.0.0:8000
python scripts\verify_production.py --url http://127.0.0.1:8000/api/health/
```

`/api/health/` 响应中 `data.readiness` 包含：

| 字段 | 含义 |
|------|------|
| `debug` | 应为 `false` |
| `database.ok` | MySQL 可连接 |
| `upload_writable.ok` | 上传目录可写 |
| `secrets.ok` | 密钥已更换 |
| `frontend_dist.ok` | 已执行 `npm run build` |
| `ready` | 以上全部满足时为 `true` |

### 步骤 27 检查清单

- [ ] `backend/.env` 自 `.env.production.example` 生成且已改密钥
- [ ] `DEBUG=False`，`DB_ENGINE=mysql`
- [ ] `python manage.py migrate` 成功
- [ ] `frontend/dist/index.html` 存在
- [ ] `verify_production.py` 通过

---

## 步骤 28：Nginx 反向代理与静态资源

目标：在 **目标服务器** 上由 Nginx 作为唯一入口，同域提供前端页面与 API。

| 路径 | 处理方式 |
|------|----------|
| `/` | 托管 `frontend/dist/`（Vue SPA，`try_files` 回退 `index.html`） |
| `/api/` | 反代到 `127.0.0.1:8000`（步骤 29 Gunicorn；验收前可临时 `runserver`） |
| `/upload/` | **默认关闭**；图片经 `/api/images/thumb/`、`/api/images/file/` 鉴权访问 |

前端生产构建已使用 `VITE_API_BASE_URL=/api`（见 `frontend/.env.production.example`），与 Nginx 同域反代一致。

### 配置文件

| 文件 | 说明 |
|------|------|
| `deploy/paths.env.example` | 服务器路径与监听参数模板 |
| `deploy/nginx/image_db.conf.template` | Nginx 站点模板 |
| `scripts/render_nginx_config.py` | 生成 `deploy/nginx/generated/image_db.conf` |
| `deploy/nginx/README.md` | 安装速查 |

### 在服务器上生成配置

```bash
cd /opt/image_db   # 项目实际路径

cp deploy/paths.env.example deploy/paths.env
# 编辑 deploy/paths.env：
#   PROJECT_ROOT=/opt/image_db
#   SERVER_NAME=192.168.1.100    # 服务器 IP 或域名
#   BACKEND_UPSTREAM=127.0.0.1:8000

python3 scripts/render_nginx_config.py
```

开发机也可用同样命令预览配置（`PROJECT_ROOT` 填本机路径，如 `E:/图像路径式数据库管理系统`）。

### 安装 Nginx（Linux 示例）

```bash
sudo apt install nginx
sudo cp deploy/nginx/generated/image_db.conf /etc/nginx/sites-available/image_db.conf
sudo ln -sf /etc/nginx/sites-available/image_db.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default   # 可选：避免默认站点冲突
sudo nginx -t && sudo systemctl reload nginx
```

### 后端 `.env` 与 Nginx 对齐

在服务器 `backend/.env` 中：

| 变量 | Nginx 同域部署建议 |
|------|-------------------|
| `ALLOWED_HOSTS` | 含 `SERVER_NAME`（IP 或域名） |
| `CORS_ALLOWED_ORIGINS` | `http://SERVER_NAME`（与浏览器访问地址一致） |
| `DEBUG` | `False` |

若使用 HTTPS，另设 `CSRF_TRUSTED_ORIGINS` 与 `SECURE_PROXY_SSL_HEADER`（见 `backend/.env.production.example`）。

### 步骤 28 验收前：临时启动后端

步骤 29 Gunicorn 就绪前，可临时使用：

```bash
cd backend
python manage.py runserver 127.0.0.1:8000
```

步骤 29 完成后改用 `systemctl start image_db` 或 `scripts/run_gunicorn.sh`。

### 验收

```powershell
# 经 Nginx 检查首页与 /api/health/
python scripts\verify_production.py --nginx-base http://192.168.1.100

# 可同时做本地就绪 + 直连 API + Nginx
python scripts\verify_production.py --url http://127.0.0.1:8000/api/health/ --nginx-base http://192.168.1.100
```

浏览器访问 `http://SERVER_NAME/` 应出现登录页；`http://SERVER_NAME/api/health/` 返回 JSON。

### 步骤 28 检查清单

- [ ] `deploy/paths.env` 已按服务器填写
- [ ] `python scripts/render_nginx_config.py` 成功
- [ ] `nginx -t` 通过并已 reload
- [ ] `frontend/dist/index.html` 存在
- [ ] 后端监听 `127.0.0.1:8000`（runserver 或 Gunicorn）
- [ ] `verify_production.py --nginx-base` 通过

### 安全说明：`/upload/` 直出

`deploy/paths.env` 中 `ENABLE_UPLOAD_DIRECT=1` 可开启 Nginx 直出 `upload/` 目录，**会绕过 API 的 JWT 鉴权**。生产环境建议保持 `0`，仅通过 `/api/images/*` 访问图片。

---

## 步骤 29：Gunicorn 守护 Django

目标：在 **Linux 服务器** 上用 Gunicorn 替代 `runserver`，监听 `127.0.0.1:8000`，供 Nginx 反代。

> Gunicorn 不支持 Windows。开发机继续用 `runserver`；生产在目标服务器部署。

### 配置文件

| 文件 | 说明 |
|------|------|
| `backend/requirements-production.txt` | 生产依赖（含 Gunicorn） |
| `deploy/gunicorn/gunicorn.conf.py` | worker、超时、日志路径 |
| `deploy/gunicorn/image_db.service.template` | systemd 单元模板 |
| `scripts/render_gunicorn_service.py` | 生成 `deploy/gunicorn/generated/image_db.service` |
| `scripts/run_gunicorn.sh` | 前台启动（调试） |
| `deploy/gunicorn/README.md` | 速查 |

### 服务器准备

```bash
cd /opt/image_db

# 虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-production.txt

# 生产 .env、migrate、前端构建（步骤 27）
python scripts/prepare_production.py --write-env
# 编辑 backend/.env 后再次 prepare 或 migrate

# 填写 deploy/paths.env（含 VENV_PATH、RUN_USER、GUNICORN_BIND）
cp deploy/paths.env.example deploy/paths.env
vim deploy/paths.env
```

`deploy/paths.env` 中与 Gunicorn 相关的项：

| 变量 | 说明 |
|------|------|
| `GUNICORN_BIND` | 与 `BACKEND_UPSTREAM` 一致，默认 `127.0.0.1:8000` |
| `GUNICORN_WORKERS` | worker 进程数，默认 `3` |
| `GUNICORN_TIMEOUT` | 请求超时（秒），上传大图建议 `120` |
| `VENV_PATH` | 虚拟环境根目录，如 `/opt/image_db/.venv` |
| `RUN_USER` / `RUN_GROUP` | systemd 运行用户，需能写 `upload/`、`backend/logs/` |

### 生成并安装 systemd

```bash
python3 scripts/render_gunicorn_service.py

sudo cp deploy/gunicorn/generated/image_db.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable image_db
sudo systemctl start image_db
sudo systemctl status image_db
```

日志：

- 应用：`backend/logs/gunicorn_access.log`、`gunicorn_error.log`
- systemd：`journalctl -u image_db -f`

### 手动启动（调试）

```bash
./scripts/run_gunicorn.sh
# 或
python3 scripts/run_gunicorn.py
```

### 与 Nginx 联调

1. Gunicorn 监听 `127.0.0.1:8000`
2. Nginx `location /api/` 反代到同一地址（步骤 28）
3. 重启顺序：先 Gunicorn，再 `nginx -t && systemctl reload nginx`

```bash
curl -s http://127.0.0.1:8000/api/health/
curl -s http://192.168.1.100/api/health/   # 经 Nginx，替换为 SERVER_NAME
```

### 验收

```powershell
# 直连 Gunicorn（在服务器或能访问 8000 的机器上）
python scripts\verify_production.py --url http://127.0.0.1:8000/api/health/

# 经 Nginx 全链路
python scripts\verify_production.py --nginx-base http://192.168.1.100
```

### 步骤 29 检查清单

- [ ] `pip install -r backend/requirements-production.txt` 成功
- [ ] `deploy/paths.env` 中 `VENV_PATH`、`GUNICORN_BIND` 已填写
- [ ] `python scripts/render_gunicorn_service.py` 成功
- [ ] `systemctl status image_db` 为 `active (running)`
- [ ] `curl http://127.0.0.1:8000/api/health/` 返回 JSON
- [ ] Nginx 反代 `/api/health/` 正常

### 运行用户权限

`RUN_USER`（如 `www-data`）需要对以下路径可写：

- `upload/`
- `backend/thumb_cache/`
- `backend/logs/`

示例（Ubuntu）：

```bash
sudo chown -R www-data:www-data upload backend/thumb_cache backend/logs
```

---

## 步骤 30：备份与冒烟测试

目标：生产环境具备 **可恢复的备份** 与 **可重复的上线验收**。

### 脚本一览

| 脚本 | 说明 |
|------|------|
| `scripts/backup_mysql.py` | MySQL 逻辑备份（`mysqldump` + gzip） |
| `scripts/backup_upload.py` | `upload/` 目录 tar.gz 归档 |
| `scripts/backup_all.py` | 一键执行上述两项 |
| `scripts/restore_mysql.py` | 从 `.sql.gz` 恢复库（需 `--yes`） |
| `scripts/smoke_test.py` | HTTP 冒烟测试 |
| `deploy/backup/cron.example` | 定时备份 crontab 示例 |
| `deploy/backup/README.md` | 速查 |

`deploy/paths.env` 可选配置：

| 变量 | 说明 |
|------|------|
| `BACKUP_ROOT` | 备份根目录，默认 `项目/backups` |
| `BACKUP_RETENTION_DAYS` | 自动清理 N 天前的备份，默认 `14` |

### 备份

依赖：服务器已安装 `mysqldump`（MySQL 客户端），`backend/.env` 中 `DB_ENGINE=mysql`。

```bash
cd /opt/image_db

# 预览
python3 scripts/backup_all.py --dry-run

# 执行
python3 scripts/backup_all.py
```

产物示例：

```
backups/mysql/image_db_20260630_020000.sql.gz
backups/upload/upload_20260630_020000.tar.gz
```

定时任务（每天凌晨 2 点）见 `deploy/backup/cron.example`。

### 恢复（谨慎）

```bash
python3 scripts/restore_mysql.py backups/mysql/image_db_YYYYMMDD_HHMMSS.sql.gz --dry-run
python3 scripts/restore_mysql.py backups/mysql/image_db_YYYYMMDD_HHMMSS.sql.gz --yes
```

`upload/` 备份解压到 `UPLOAD_ROOT`（默认 `upload/`）即可还原图片文件。

### 冒烟测试

在 Gunicorn（及可选 Nginx）运行后执行：

```bash
# 直连后端
python3 scripts/smoke_test.py --base-url http://127.0.0.1:8000

# 经 Nginx 全链路（推荐上线验收）
python3 scripts/smoke_test.py --base-url http://192.168.1.100
```

默认账号 `admin / admin123`（种子数据）；生产请指定实际管理员：

```bash
python3 scripts/smoke_test.py --base-url http://192.168.1.100 --username admin --password '你的密码'
```

检查流程：

1. `GET /api/health/`
2. `POST /api/auth/login/`
3. `GET /api/auth/me/`
4. `GET /api/images/categories/`
5. `GET /api/images/`
6. `GET /api/config/`（管理员）
7. `GET /api/logs/stats/`

### 上线验收组合命令

```powershell
# 本地就绪 + 直连 API + Nginx + 冒烟
python scripts\verify_production.py --url http://127.0.0.1:8000/api/health/ --nginx-base http://192.168.1.100
python scripts\smoke_test.py --base-url http://192.168.1.100
```

### 步骤 30 检查清单

- [ ] `python scripts/backup_all.py --dry-run` 命令正确
- [ ] `python scripts/backup_all.py` 生成 mysql 与 upload 备份文件
- [ ] `BACKUP_RETENTION_DAYS` 过期清理符合预期
- [ ] `smoke_test.py` 经 Nginx 全部 PASS
- [ ] 已配置 crontab 或等价定时任务
- [ ] 恢复步骤已在演练环境验证（可选但推荐）

---

## 后续步骤（31~33 概要）

| 步骤 | 内容 |
|------|------|
| 31 | 定时维护任务 |
| 32 | 健康监控 |
| 33 | 用户手册与交付文档 |
