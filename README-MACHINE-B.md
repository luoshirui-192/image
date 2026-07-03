# 机器 B 部署指南（数据层）

本分支用于 **双机部署** 中的 **机器 B**：提供 **MySQL 主库** 与 **upload 图片存储**，并通过 **NFS** 供机器 A 挂载。

| 机器 | 职责 |
|------|------|
| **B（本机）** | MySQL `image_db`、图片目录、NFS 导出 |
| **A（应用机）** | Docker Web/Backend，连接 B 的库与 NFS |

机器 B **不需要**对外提供 HTTP 页面，也 **不需要** clone 后跑 `start.sh`（单机版）。

应用层部署见分支 **[deploy/machine-a](https://github.com/luoshirui-192/image/tree/deploy/machine-a)** 与 [README-MACHINE-A.md](https://github.com/luoshirui-192/image/blob/deploy/machine-a/README-MACHINE-A.md)。

---

## 架构

```
机器 A                          机器 B（本机）
┌─────────────┐                ┌──────────────────────┐
│ web/backend │─── MySQL ─────►│ Docker MySQL :3306   │
│             │─── NFS 读写 ──►│ /data/.../upload/    │
└─────────────┘                └──────────────────────┘
     ▲
  用户浏览器
```

---

## 快速开始（Docker MySQL，推荐）

```bash
git clone -b deploy/machine-b https://github.com/luoshirui-192/image.git
cd image

cp .env.data.example .env
# 编辑：MYSQL_* 密码、MACHINE_A_HOSTS（A 的 IP）、DATA_UPLOAD_ROOT

chmod +x start-data.sh scripts/*.sh
./start-data.sh
./scripts/grant-machine-a.sh
./scripts/setup-nfs-export.sh
```

完成后告知机器 A 管理员：

- `DB_HOST=<本机 B 的内网 IP>`
- `MYSQL_PASSWORD=` 与 B 的 `.env` 一致
- NFS：`mount -t nfs <B_IP>:/data/image_db/upload /opt/image_db/upload`

---

## 环境要求

| 项目 | 建议 |
|------|------|
| 操作系统 | Linux（Ubuntu 22.04 / Debian 12） |
| CPU / 内存 | 2 核、4GB+（视数据量增大） |
| 磁盘 | 系统盘 + **大容量数据盘** 存 MySQL 与 upload |
| 软件 | Git、Docker、Docker Compose；NFS 用 `nfs-kernel-server` |
| 网络 | 内网固定 IP；对 **机器 A** 开放 3306、2049 |

---

## 配置 `.env`

```bash
cp .env.data.example .env
```

| 变量 | 说明 | 示例 |
|------|------|------|
| `MYSQL_ROOT_PASSWORD` | MySQL root 密码 | 强密码 |
| `MYSQL_PASSWORD` | 应用用户密码（A 的 `.env` 须一致） | 强密码 |
| `MYSQL_DATABASE` | 库名 | `image_db` |
| `MYSQL_USER` | 应用用户 | `image_db` |
| `MYSQL_PUBLISH_PORT` | 对外 MySQL 端口 | `3306` |
| `DATA_UPLOAD_ROOT` | 宿主机图片目录 | `/data/image_db/upload` |
| `NFS_EXPORT_PATH` | NFS 导出路径（通常同上） | `/data/image_db/upload` |
| `MACHINE_A_HOSTS` | 机器 A 的 IP（可多个，空格分隔） | `192.168.1.10` |

---

## 分步部署

### 1. 启动 MySQL

```bash
./start-data.sh
```

首次启动会自动执行 `sql/` 初始化脚本（含 `blob_migration.sql`），并创建默认账号 **admin / admin123**。

验证：

```bash
docker compose -f docker-compose.data.yml ps
docker compose -f docker-compose.data.yml exec db \
  mysql -u image_db -p"${MYSQL_PASSWORD}" -e "SELECT COUNT(*) FROM image_db.sys_user;"
```

### 2. 授权机器 A 连接数据库

```bash
./scripts/grant-machine-a.sh
```

为 `.env` 中 `MACHINE_A_HOSTS` 里的每个 IP 创建 `'image_db'@'A_IP'` 并授权。

### 3. 配置 NFS 导出 upload

```bash
./scripts/setup-nfs-export.sh
```

将 `DATA_UPLOAD_ROOT` 导出给机器 A。脚本会写入 `/etc/exports` 并重启 nfs-server。

**机器 A 挂载示例：**

```bash
sudo mkdir -p /opt/image_db/upload
sudo mount -t nfs 192.168.1.20:/data/image_db/upload /opt/image_db/upload
```

### 4. 防火墙（仅放行 A）

```bash
# UFW 示例（B 上）
sudo ufw allow from 192.168.1.10 to any port 3306
sudo ufw allow from 192.168.1.10 to any port 2049
```

**不要**对公网开放 3306 / NFS。

---

## 方式二：系统自带 MySQL（不用 Docker）

若 B 上已有 MySQL 8.0，可不跑 `start-data.sh`，手工初始化：

```bash
mysql -u root -p < sql/image_db.sql
mysql -u root -p image_db < sql/optimize_indexes.sql
mysql -u root -p image_db < sql/fix_mysql57_triggers.sql
mysql -u root -p image_db < sql/seed_test_data.sql
mysql -u root -p image_db < sql/blob_migration.sql
```

然后手工执行 `grant-machine-a.sh` 中的 SQL（将 `docker compose exec` 改为本机 `mysql`），再配置 NFS。

`my.cnf` 需 `bind-address = 0.0.0.0` 或内网 IP，并重启 MySQL。

---

## 与机器 A 的密码对齐

机器 A（`deploy/machine-a` 分支）的 `.env` 中：

```env
DB_HOST=<B 的 IP>
MYSQL_PASSWORD=<与 B 的 MYSQL_PASSWORD 相同>
MYSQL_USER=image_db
MYSQL_DATABASE=image_db
```

两边密码、库名、用户名必须一致。

---

## 备份

**数据库：**

```bash
docker compose -f docker-compose.data.yml exec db \
  mysqldump -u root -p"${MYSQL_ROOT_PASSWORD}" image_db > backup_$(date +%F).sql
```

**图片：**

```bash
tar czf upload_$(date +%F).tar.gz -C /data/image_db upload
```

建议定期备份到独立存储。

---

## 常用命令

```bash
docker compose -f docker-compose.data.yml ps
docker compose -f docker-compose.data.yml logs -f db
docker compose -f docker-compose.data.yml down        # 停止（数据卷保留）
docker compose -f docker-compose.data.yml down -v     # 停止并删库（慎用）
```

---

## 故障排查

| 现象 | 处理 |
|------|------|
| A 连不上 MySQL | B 防火墙；`grant-machine-a.sh` 是否执行；`telnet B_IP 3306` |
| A 上传失败 | NFS 是否挂载；B 上 `exportfs -v`；目录权限 |
| 初始化重复 | 已有 `mysql_data` 卷时不会重跑 sql；需 `down -v` 后重建（会丢数据） |
| NFS 权限 denied | exports 使用 `no_root_squash`；A 容器以 root 写文件 |

---

## 本分支专用文件

| 文件 | 用途 |
|------|------|
| `docker-compose.data.yml` | 仅 MySQL 容器 |
| `.env.data.example` | 环境变量模板 |
| `docker/mysql-init/00-init-data.sh` | 首次建库（含 BLOB 表） |
| `start-data.sh` / `start-data.ps1` | 启动 MySQL |
| `scripts/grant-machine-a.sh` | 授权 A 连接 |
| `scripts/setup-nfs-export.sh` | 配置 NFS |
| `README-MACHINE-B.md` | 本文档 |

---

## 相关链接

- 机器 A 部署：[deploy/machine-a](https://github.com/luoshirui-192/image/tree/deploy/machine-a)
- 单机 all-in-one：`main` 分支 [README.md](README.md)
- 仓库：https://github.com/luoshirui-192/image.git
