# 机器 A 部署指南（数据库 + 服务端）

本分支用于 **双机部署** 中的 **机器 A**：运行 **MySQL 主库**、**Web / Backend / Scheduler**，通过 **S3 SDK 直连 MinIO** 读写图片。

| 机器 | 职责 |
|------|------|
| **A（本机）** | MySQL `image_db`、Docker 应用、对外 HTTP |
| **B（存储配置）** | 对接 MinIO VIP `192.168.9.9`，初始化 `biox/data/image_db/` 前缀 |

其他办公电脑通过浏览器访问 **A 的 `PUBLIC_URL`** 即可使用全部 Web 功能。图片文件存储在 **MinIO**（非 A 本地磁盘）。

存储层配置见分支 **[deploy/machine-b](https://github.com/luoshirui-192/image/tree/deploy/machine-b)** 与 [README-MACHINE-B.md](https://github.com/luoshirui-192/image/blob/deploy/machine-b/README-MACHINE-B.md)。

---

## 架构

```
用户浏览器
     │
     ▼
机器 A（本机）                         192.168.9.9 MinIO VIP
┌─────────────────────┐   S3 API      ┌──────────────────────────┐
│ web / backend       │──────────────►│ biox/data/image_db/upload│
│ MySQL (Docker db)   │   (9000)      │        ↓ 101/102 节点    │
└─────────────────────┘               └──────────────────────────┘
```

---

## 快速开始

**先完成机器 B 侧 MinIO 前缀初始化**，再部署 A。

```bash
git clone -b deploy/machine-a https://github.com/luoshirui-192/image.git
cd image

cp .env.app.example .env
# 编辑：PUBLIC_URL、MYSQL_* 密码、MINIO_* 密钥

chmod +x start-app.sh
./start-app.sh
```

浏览器打开 `.env` 里的 `PUBLIC_URL`，默认账号 **admin / admin123**。

---

## 前置条件：机器 B / MinIO 必须先就绪

在部署 A 之前需确认：

1. **机器 B** 已运行 `./scripts/setup-minio-prefix.sh`（或管理员已创建 `biox/data/image_db/` 前缀）
2. MinIO 账号对 `biox/data/image_db/*` 有读写删权限
3. **机器 A**（及 Docker 容器）能访问 `192.168.9.9:9000`

```bash
curl http://192.168.9.9:9000/minio/health/live
```

> 不再使用 NFS 挂载 `./upload`。`STORAGE_BACKEND=minio` 时图片经 S3 API 存取。

---

## 机器 A 环境要求

- Linux（推荐 Ubuntu 22.04 / Debian 12）或 Windows + Docker Desktop
- Git、Docker Engine、Docker Compose 插件
- 4GB+ 内存（首次构建前端镜像）
- 项目路径建议 **纯英文**（Windows Docker 限制）
- 能访问 MinIO VIP **192.168.9.9:9000**

---

## 配置 `.env`

```bash
cp .env.app.example .env
```

| 变量 | 说明 | 示例 |
|------|------|------|
| `PUBLIC_URL` | **A** 的访问地址 | `http://192.168.17.162` |
| `HTTP_PORT` | A 对外端口 | `80` |
| `MYSQL_ROOT_PASSWORD` | 本机 MySQL root 密码 | 强密码 |
| `MYSQL_PASSWORD` | 应用库用户密码 | 强密码 |
| `STORAGE_BACKEND` | 存储后端 | `minio`（生产）/ `local`（调试） |
| `MINIO_ENDPOINT` | MinIO VIP | `http://192.168.9.9:9000` |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | MinIO 凭证 | B 侧交接 |
| `MINIO_BUCKET` | 桶名 | `biox` |
| `MINIO_PREFIX` | 对象前缀 | `data/image_db` |
| `SECRET_KEY` | Django 密钥 | `python3 scripts/generate_secret_key.py` |
| `IMAGE_ACCESS_SECRET` | 图片令牌密钥 | 再生成一段 |

`ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS` 由 `docker/set-env.py` 根据 `PUBLIC_URL` **自动写入**。

MySQL 在 A 本机 Docker 容器 `db` 内，**无需**配置 `DB_HOST` 指向 B。

---

## 验证 MinIO 连通性

在 A 上（启动前）：

```bash
# 宿主机
curl http://192.168.9.9:9000/minio/health/live

# 启动后容器内
docker compose -f docker-compose.app.yml exec backend \
  python scripts/init_storage.py
```

健康检查 `/api/health/` 的 `readiness.upload_writable` 会对 MinIO 做写入探针。

---

## 启动与停止

```bash
chmod +x start-app.sh scripts/compose-app-args.sh
./start-app.sh
```

`start-app.sh` 会**自动**选择 MySQL 连接方式：

| 条件 | backend 连接 |
|------|----------------|
| 存在 `docker-compose.app.override.yml` | 按 override（推荐：宿主机 **mysql8039**） |
| `.env` 中 `USE_EXTERNAL_MYSQL=1` | `host.docker.internal:3306` |
| 否则 | compose 内置 `db` 容器 |

**使用宿主机已有 MySQL（如 mysql8039）时，任选其一：**

```bash
# 方式 A：保留 override（推荐，一次配置永久生效）
cp docker-compose.app.external-db.example.yml docker-compose.app.override.yml
# 确认 .env 中 MYSQL_DATABASE / MYSQL_USER / DB_PASSWORD 与 mysql8039 一致

# 方式 B：仅用 .env 开关
# 在 .env 增加：USE_EXTERNAL_MYSQL=1
```

重启前确保宿主机 MySQL 已启动：

```bash
docker start mysql8039
./start-app.sh
```

**停止**（与启动相同 compose 文件组合，含 override 时须带上）：

```bash
docker compose -f docker-compose.app.yml -f docker-compose.app.override.yml down
```

---

## 与单机部署（main 分支）的区别

| 项目 | main 分支 `start.sh` | 本分支 `start-app.sh` |
|------|----------------------|------------------------|
| Compose 文件 | `docker-compose.yml` | `docker-compose.app.yml` |
| 环境模板 | `.env.docker.example` | `.env.app.example` |
| MySQL | ✅ 本地容器 | ✅ 本地容器 |
| 图片存储 | 本地 `./upload` | **MinIO S3（9.100）** |
| 适用场景 | 一台机器 all-in-one | A 库+服务 + B MinIO 配置 |

---

## 功能说明

- 上传、**BLOB 数据浏览**（含 SQL 查询）、BLOB 迁移、分类管理
- 连接**外部旧库**迁 BLOB：由 **A 的 backend 容器**发起连接，旧库需允许 **A 的 IP** 访问
- 元数据写入 **A 的 MySQL**；图片文件写入 **MinIO** `biox/data/image_db/upload/...`
- 数据库 `image_path` 仍为 `upload/{date}/{category}/{uuid}.ext` 相对路径

缩略图缓存 `thumb_cache` 在 A 本地 Docker 卷，丢失可自动重建。

---

## 本地调试（不用 MinIO）

`.env` 中设置：

```env
STORAGE_BACKEND=local
```

并在 `docker-compose.app.yml` 的 backend/scheduler 中临时恢复 upload 卷挂载：

```yaml
volumes:
  - ./upload:/app/upload
  - thumb_cache:/app/backend/thumb_cache
```

---

## 备份

**数据库（A 上）：**

```bash
docker compose -f docker-compose.app.yml exec db \
  mysqldump -u root -p"${MYSQL_ROOT_PASSWORD}" image_db > backup_$(date +%F).sql
```

**图片（MinIO）：**

```bash
mc mirror aratek/biox/data/image_db/upload/ ./backup_upload/
```

详见 [README-MACHINE-B.md](https://github.com/luoshirui-192/image/blob/deploy/machine-b/README-MACHINE-B.md)。

---

## BLOB 数据浏览与迁移

1. **外部库连接**：在「BLOB 迁移」页配置 MySQL 连接（迁移目标库为 `external_db_connection.db_name`）。
2. **迁移**：选择表或数据库视图，勾选全部 BLOB 列后执行后台迁移任务。
3. **浏览**：在「BLOB 数据浏览」左侧目录树选择连接 → 库 → 表/数据库视图；可保存为浏览配置。
4. **SQL**：同一页面的「SQL 查询」Tab 针对当前选中的连接与库执行 `SELECT`。
5. **Schema 升级**：backend 启动时自动执行 `schema_ensure`（PR1 起增加 `source_column`、`blob_columns` 等字段）。

旧路由 `/blob-views`、`/sql` 会自动跳转到 `/blob-browse`。

### 部署后验证

```bash
# 健康检查
curl -s http://127.0.0.1/api/health/ | python3 -m json.tool

# 冒烟测试（含 BLOB 目录与浏览配置 API）
python3 scripts/smoke_test.py --base-url http://127.0.0.1

# 单元测试（开发机 / CI）
cd backend && DB_ENGINE=sqlite python manage.py test images sqlquery -v 1
```

---

## 故障排查

| 现象 | 处理 |
|------|------|
| **每次重启后表数据「已加载 0」** | 未用 override / `USE_EXTERNAL_MYSQL=1`，backend 连到**空的 compose db** 而非 **mysql8039**。执行 `docker compose ... exec backend env \| grep DB_HOST`，应为 `host.docker.internal`；然后 `docker start mysql8039` 并用 `./start-app.sh` 重启 |
| backend 一直 waiting for MySQL | `docker compose -f docker-compose.app.yml logs db`；检查 `.env` 密码 |
| 上传/预览失败 | `STORAGE_BACKEND=minio`；MinIO 凭证；容器能否访问 9.100:9000 |
| readiness upload 失败 | 运行 `python scripts/init_storage.py`；检查 MINIO_* 配置 |
| 502 | `docker compose -f docker-compose.app.yml logs backend` |
| 连旧库失败 | 旧库防火墙放行 **A 的 IP** |

---

## 文件清单（机器 A 专用）

| 文件 | 用途 |
|------|------|
| `docker-compose.app.yml` | db + web + backend + scheduler（MinIO 环境变量） |
| `.env.app.example` | 环境变量模板 |
| `backend/utils/storage.py` | local / minio 存储后端 |
| `start-app.sh` / `start-app.ps1` | 一键启动 |
| `docker-compose.app.external-db.example.yml` | 使用宿主机 MySQL 时的 compose 覆盖示例 |
| `README-MACHINE-A.md` | 本文档 |

---

## 相关链接

- 机器 B MinIO 配置：[deploy/machine-b](https://github.com/luoshirui-192/image/tree/deploy/machine-b)
- 单机 all-in-one：`main` 分支 [README.md](README.md)
