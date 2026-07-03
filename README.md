# 图像路径式数据库管理系统

图片元数据与路径分离存储的 Web 管理系统：支持上传、BLOB 迁移、SQL 自定义查询、远程表视图浏览与图片预览。

**推荐部署方式：Docker Compose 一键启动**（无需单独安装 Python、Node、MySQL、Nginx）。

**双机部署（应用机 A + 数据机 B）** 请使用分支 [`deploy/machine-a`](README-MACHINE-A.md)，阅读 [README-MACHINE-A.md](README-MACHINE-A.md)。

---

## 功能概览

| 功能 | 说明 | 权限 |
|------|------|------|
| 图片上传 | 拖拽/多选上传，分类与标签 | 所有登录用户 |
| BLOB 迁移 | 从旧库 BLOB 字段导出到 `upload/` 并写入路径表 | 所有登录用户 |
| BLOB 表视图 | 浏览远程旧表，BLOB 列显示为本地路径 | 所有登录用户 |
| SQL 查询 | 自定义 `SELECT`，结果可预览/下载/编辑/删除 | 所有登录用户 |
| 分类管理 | 维护图片分类 | 所有登录用户 |
| 操作日志 | SQL 与上传/删除记录 | 仅管理员 |
| 系统设置 | 上传限制、SQL 超时等参数 | 仅管理员 |

默认管理员账号：**admin / admin123**（首次登录后建议修改密码）。

---

## 系统架构

```
浏览器  →  http://服务器IP:端口
              │
              ▼
         ┌─────────┐     ┌──────────┐     ┌─────────┐
         │   web   │────►│ backend  │────►│   db    │
         │ Nginx   │     │ Gunicorn │     │ MySQL   │
         │ + 前端  │     │ Django   │     │  8.0    │
         └─────────┘     └──────────┘     └─────────┘
              │                │
              │           ┌────┴────┐
              │           │scheduler│  定时清理日志/软删文件
              │           └─────────┘
              │
         图片经 /api/images/* 鉴权访问（不直接暴露 upload/ 目录）
```

Docker 会自动启动 4 个服务：`db`、`backend`、`web`、`scheduler`。

---

## 环境要求

| 项目 | 建议 |
|------|------|
| 操作系统 | **Linux**（Ubuntu 22.04 / Debian 12 等，生产首选）；Windows 需 Docker Desktop |
| CPU / 内存 | 2 核、**4GB+** 内存（首次构建前端镜像较耗内存） |
| 磁盘 | 20GB+（视图片存储量增减） |
| 软件 | Git、Docker Engine、Docker Compose 插件 |

---

## 从零部署（Docker）

### 1. 安装 Docker

**Linux（Ubuntu / Debian）：**

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# 重新登录 SSH 后生效
docker --version
docker compose version
```

**Windows：** 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/) 并保持运行。

> **Windows 注意：** 项目路径不能含中文或非 ASCII 字符，否则 Docker 构建会失败。请克隆到纯英文路径，例如 `E:\image_db`。

### 2. 克隆代码

```bash
git clone https://github.com/luoshirui-192/image.git
cd image
```

### 3. 创建并编辑 `.env`

```bash
cp .env.docker.example .env
```

用编辑器打开项目根目录的 `.env`，按需修改以下项：

| 变量 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `PUBLIC_URL` | **是** | 浏览器访问地址，**不要**末尾斜杠 | `http://192.168.1.100` |
| `HTTP_PORT` | 否 | 对外 HTTP 端口，默认 80 | `80` 或 `8080` |
| `MYSQL_ROOT_PASSWORD` | **是** | MySQL root 密码，生产务必改强密码 | 自行设定 |
| `MYSQL_PASSWORD` | **是** | 应用连接 MySQL 的密码 | 自行设定 |
| `MYSQL_DATABASE` | 否 | 数据库名，默认 `image_db` | `image_db` |
| `MYSQL_USER` | 否 | 数据库用户，默认 `image_db` | `image_db` |
| `SECRET_KEY` | **是** | Django 密钥，生产必须随机 | 见下方生成方式 |
| `IMAGE_ACCESS_SECRET` | **是** | 图片访问令牌密钥，与 SECRET_KEY 分开设置 | 见下方生成方式 |
| `LOG_RETENTION_DAYS` | 否 | 操作日志保留天数，默认 90 | `90` |
| `DELETED_IMAGE_RETENTION_DAYS` | 否 | 历史软删文件清理保留天数，默认 30 | `30` |
| `MAINTENANCE_INTERVAL_HOURS` | 否 | 定时维护间隔（小时），默认 24 | `24` |

**生成随机密钥：**

```bash
python3 scripts/generate_secret_key.py
# 运行两次，分别填入 SECRET_KEY 和 IMAGE_ACCESS_SECRET
```

**`.env` 配置示例（局域网部署）：**

```env
PUBLIC_URL=http://192.168.1.100
HTTP_PORT=80

MYSQL_ROOT_PASSWORD=YourStrongRootPass
MYSQL_PASSWORD=YourStrongAppPass
MYSQL_DATABASE=image_db
MYSQL_USER=image_db

SECRET_KEY=这里填随机字符串
IMAGE_ACCESS_SECRET=这里填另一段随机字符串

LOG_RETENTION_DAYS=90
DELETED_IMAGE_RETENTION_DAYS=30
MAINTENANCE_INTERVAL_HOURS=24
```

> `ALLOWED_HOSTS` 和 `CORS_ALLOWED_ORIGINS` **无需手写**。启动脚本会根据 `PUBLIC_URL` 自动写入（见 `docker/set-env.py`）。

### 4. 一键启动

**Linux / macOS：**

```bash
chmod +x start.sh
./start.sh
```

**Windows PowerShell：**

```powershell
.\start.ps1
```

脚本会自动：

1. 若不存在 `.env`，从 `.env.docker.example` 复制一份
2. 根据 `PUBLIC_URL` 同步 `ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS`
3. 构建镜像并启动全部容器
4. 等待 MySQL 就绪 → 自动 `migrate` → 启动 Gunicorn 与 Nginx

首次构建约需 **5～15 分钟**（下载镜像 + 编译前端）。

### 5. 访问系统

浏览器打开 `.env` 中配置的地址，例如：

- `http://192.168.1.100`（`HTTP_PORT=80`）
- `http://192.168.1.100:8080`（`HTTP_PORT=8080`）

登录：**admin / admin123**

---

## 修改配置后如何生效

编辑 `.env` 后重新执行启动脚本即可：

```bash
./start.sh          # Linux / macOS
.\start.ps1         # Windows
```

或手动：

```bash
python3 docker/set-env.py
docker compose up -d --build
```

---

## 常用运维命令

```bash
docker compose ps                  # 查看容器状态
docker compose logs -f backend   # 后端日志
docker compose logs -f web       # Nginx 日志
docker compose logs -f scheduler # 定时维护日志
docker compose down              # 停止服务
docker compose down -v           # 停止并删除数据卷（会清空数据库，慎用）
```

---

## 数据存储位置

| 位置 | 内容 | 说明 |
|------|------|------|
| Docker 卷 `mysql_data` | MySQL 数据库 | 容器重建不丢失 |
| 目录 `./upload/` | 上传的图片原文件 | 建议定期备份 |
| Docker 卷 `thumb_cache` | 缩略图缓存 | 可重建 |
| 文件 `.env` | 密钥与配置 | **不要提交到 Git** |

**备份数据库示例：**

```bash
docker compose exec db mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" image_db > backup.sql
```

**备份图片：**

```bash
tar czf upload_backup.tar.gz upload/
```

---

## 从另一台机器迁移

Git 仓库只包含代码，不含运行时数据。迁移步骤：

1. 在新服务器按上文「从零部署」克隆代码、配置 `.env`、启动 Docker
2. 拷贝旧机器的 `upload/` 目录到新项目根目录
3. 如需保留数据库，在旧机器导出 `mysqldump`，在新机器导入：

```bash
# 旧机器
docker compose exec db mysqldump -u root -p image_db > image_db.sql

# 新机器（服务已启动）
docker compose exec -T db mysql -u root -p image_db < image_db.sql
```

---

## 故障排查

| 现象 | 处理 |
|------|------|
| 首次启动很慢 | 正常，需下载镜像并 `npm ci` 构建前端 |
| 502 Bad Gateway | `docker compose logs backend`，等 MySQL 初始化完成（约 1 分钟） |
| 登录失败 / 接口 403 | 检查 `.env` 中 `PUBLIC_URL` 是否与浏览器地址一致，改完后重新 `./start.sh` |
| 端口 80 被占用 | `.env` 改 `HTTP_PORT=8080`，访问 `http://IP:8080` |
| Windows 构建失败 | 确认项目路径为纯英文，如 `E:\image_db` |
| 页面仍是旧版 | 浏览器 **Ctrl+F5** 强制刷新 |
| 外网/局域网无法访问 | 检查防火墙是否放行 `HTTP_PORT`；MySQL 3306 勿对公网开放 |

---

## 项目结构

```
├── backend/              Django + DRF 后端
├── frontend/             Vue 3 前端
├── upload/               图片存储目录（运行时数据）
├── sql/                  MySQL 初始化脚本
├── docker/               Docker 配置与入口脚本
├── docker-compose.yml    服务编排
├── .env.docker.example   环境变量模板
├── start.sh / start.ps1  一键启动脚本
├── deploy/               裸机 Nginx + Gunicorn 配置（可选）
└── scripts/              辅助脚本
```

---

## 开发模式（修改代码时）

需要本地分别启动后端与前端，详见：

- 后端：`backend/README.md`
- 前端：`frontend/README.md`

生产环境请继续使用 Docker 部署。

---

## 裸机部署（不用 Docker）

若需在已有 Linux 服务器上手工安装 Nginx + Gunicorn + MySQL，参见：

- [docs/deploy.md](docs/deploy.md)
- [服务器部署完整指南.md](服务器部署完整指南.md)

---

## 技术栈

- **后端：** Django 5 + DRF + SimpleJWT + MySQL 8.0
- **前端：** Vue 3 + Vite + Element Plus + Pinia
- **存储：** `upload/YYYYMMDD/category_id/uuid.ext`
- **部署：** Docker Compose（MySQL + Gunicorn + Nginx + 定时维护）

---

## 许可证

见仓库内 LICENSE 文件（如有）。
