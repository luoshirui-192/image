# 机器 A 部署指南（数据库 + 服务端）

本分支用于 **双机部署** 中的 **机器 A**：运行 **MySQL 主库**、**Web / Backend / Scheduler**，对外提供 HTTP 服务。

| 机器 | 职责 |
|------|------|
| **A（本机）** | MySQL `image_db`、Docker 应用、对外 HTTP |
| **B（存储机）** | 仅 `upload/` 图片目录 + NFS 导出 |

其他办公电脑通过浏览器访问 **A 的 `PUBLIC_URL`** 即可使用全部 Web 功能。图片文件经 NFS 读写 **B** 的磁盘。

存储层部署见分支 **[deploy/machine-b](https://github.com/luoshirui-192/image/tree/deploy/machine-b)** 与 [README-MACHINE-B.md](https://github.com/luoshirui-192/image/blob/deploy/machine-b/README-MACHINE-B.md)。

---

## 架构

```
用户浏览器
     │
     ▼
机器 A（本机）                    机器 B（存储）
┌─────────────────────┐          ┌──────────────────┐
│ web / backend       │          │ /data/.../upload │
│ MySQL (Docker db)   │── NFS ──►│ NFS 导出         │
└─────────────────────┘          └──────────────────┘
```

---

## 快速开始

**先部署机器 B**（NFS 存储），再部署 A。

```bash
git clone -b deploy/machine-a https://github.com/luoshirui-192/image.git
cd image

cp .env.app.example .env
# 编辑：PUBLIC_URL、MYSQL_* 密码、MACHINE_B_NFS_*（B 的 IP 与路径）

# 挂载机器 B 的 upload（生产必做）
sudo mount -t nfs 192.168.1.20:/data/image_db/upload ./upload

chmod +x start-app.sh
./start-app.sh
```

浏览器打开 `.env` 里的 `PUBLIC_URL`，默认账号 **admin / admin123**。

---

## 前置条件：机器 B 必须先就绪

在部署 A 之前，**机器 B** 需完成：

1. 创建图片目录（如 `/data/image_db/upload`）
2. 配置 **NFS 导出** 给 A 的 IP
3. 防火墙对 **A 的 IP** 开放 **2049**（NFS）

> 机器 B **不需要** MySQL，也 **不需要** Docker。详见 [README-MACHINE-B.md](README-MACHINE-B.md)。

---

## 机器 A 环境要求

- Linux（推荐 Ubuntu 22.04 / Debian 12）或 Windows + Docker Desktop
- Git、Docker Engine、Docker Compose 插件
- 4GB+ 内存（首次构建前端镜像）
- 项目路径建议 **纯英文**（Windows Docker 限制）
- 能访问 B 的 **NFS**（2049）

---

## 配置 `.env`

```bash
cp .env.app.example .env
```

| 变量 | 说明 | 示例 |
|------|------|------|
| `PUBLIC_URL` | **A** 的访问地址 | `http://192.168.1.10` |
| `HTTP_PORT` | A 对外端口 | `80` |
| `MYSQL_ROOT_PASSWORD` | 本机 MySQL root 密码 | 强密码 |
| `MYSQL_PASSWORD` | 应用库用户密码 | 强密码 |
| `MYSQL_DATABASE` | 库名 | `image_db` |
| `MYSQL_USER` | 库用户 | `image_db` |
| `MYSQL_PUBLISH_PORT` | 本机映射 MySQL 端口 | `3306`（仅 127.0.0.1） |
| `MACHINE_B_NFS_HOST` | **B** 的 IP（供挂载参考） | `192.168.1.20` |
| `MACHINE_B_NFS_PATH` | B 上 NFS 导出路径 | `/data/image_db/upload` |
| `SECRET_KEY` | Django 密钥 | `python3 scripts/generate_secret_key.py` |
| `IMAGE_ACCESS_SECRET` | 图片令牌密钥 | 再生成一段 |

`ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS` 由 `docker/set-env.py` 根据 `PUBLIC_URL` **自动写入**。

MySQL 在 A 本机 Docker 容器 `db` 内，**无需**配置 `DB_HOST` 指向 B。

---

## NFS 挂载 upload

Backend 将 `./upload` 映射为容器内 `/app/upload`，**生产环境必须挂载 B 的 NFS**。

**Linux（A 上）：**

```bash
sudo mkdir -p /opt/image_db/upload
sudo mount -t nfs 192.168.1.20:/data/image_db/upload /opt/image_db/upload
```

若项目在 `/opt/image_db`，则 `./upload` 即为该挂载点。

**开机自动挂载**（`/etc/fstab`）：

```
192.168.1.20:/data/image_db/upload  /opt/image_db/upload  nfs  defaults,_netdev  0  0
```

**验证：**

```bash
touch upload/.nfs_test && rm upload/.nfs_test
# 在 B 上应能看到该文件
```

---

## 启动与停止

```bash
chmod +x start-app.sh
./start-app.sh
```

等价命令：

```bash
python3 docker/set-env.py
docker compose -f docker-compose.app.yml up -d --build
```

**Windows：**

```powershell
.\start-app.ps1
```

**停止：**

```bash
docker compose -f docker-compose.app.yml down
```

**查看状态：**

```bash
docker compose -f docker-compose.app.yml ps
docker compose -f docker-compose.app.yml logs -f backend
```

---

## 与单机部署（main 分支）的区别

| 项目 | main 分支 `start.sh` | 本分支 `start-app.sh` |
|------|----------------------|------------------------|
| Compose 文件 | `docker-compose.yml` | `docker-compose.app.yml` |
| 环境模板 | `.env.docker.example` | `.env.app.example` |
| MySQL | ✅ 本地容器 | ✅ 本地容器 |
| upload | 本地目录 | **NFS 来自 B** |
| 适用场景 | 一台机器 all-in-one | A 库+服务 + B 纯存储 |

---

## 功能说明

- 上传、SQL 查询、BLOB 迁移、BLOB 表视图、分类管理
- 连接**外部旧库**迁 BLOB：由 **A 的 backend 容器**发起连接，旧库需允许 **A 的 IP** 访问
- 元数据写入 **A 的 MySQL**；图片文件写入 **B 的 upload**（经 NFS）

缩略图缓存 `thumb_cache` 在 A 本地 Docker 卷，丢失可自动重建。

---

## 备份

**数据库（A 上）：**

```bash
docker compose -f docker-compose.app.yml exec db \
  mysqldump -u root -p"${MYSQL_ROOT_PASSWORD}" image_db > backup_$(date +%F).sql
```

**图片（B 上）：**

在 B 上对 `DATA_UPLOAD_ROOT` 做 tar 备份，见 [README-MACHINE-B.md](README-MACHINE-B.md)。

---

## 故障排查

| 现象 | 处理 |
|------|------|
| backend 一直 waiting for MySQL | `docker compose -f docker-compose.app.yml logs db`；检查 `.env` 密码 |
| 上传/预览失败 | NFS 是否挂载到 `./upload`；B 上 `exportfs -v`；目录权限 |
| 502 | `docker compose -f docker-compose.app.yml logs backend` |
| 登录失败 | 首次启动是否完成 sql 初始化；`seed_test_data.sql` |
| 连旧库失败 | 旧库防火墙放行 **A 的 IP** |

**测试本机数据库：**

```bash
docker compose -f docker-compose.app.yml exec backend \
  python -c "import django; django.setup(); from django.db import connection; connection.ensure_connection(); print('ok')"
```

---

## 文件清单（机器 A 专用）

| 文件 | 用途 |
|------|------|
| `docker-compose.app.yml` | db + web + backend + scheduler |
| `.env.app.example` | 环境变量模板 |
| `docker/mysql-init/00-init-app.sh` | 首次建库（含 BLOB 表） |
| `start-app.sh` / `start-app.ps1` | 一键启动 |
| `README-MACHINE-A.md` | 本文档 |

---

## 相关链接

- 机器 B 存储：[deploy/machine-b](https://github.com/luoshirui-192/image/tree/deploy/machine-b)
- 单机 all-in-one：`main` 分支 [README.md](README.md)
- 仓库：https://github.com/luoshirui-192/image.git
