# 机器 A 部署指南（应用层）

本分支用于 **双机部署** 中的 **机器 A**：只跑 Web / Backend / Scheduler，**不包含 MySQL 容器**。

| 机器 | 职责 |
|------|------|
| **A（本机）** | Docker 应用、对外 HTTP、连接 B 的库与 NFS |
| **B（数据机）** | MySQL 主库 + `upload/` 图片目录 + NFS 导出 |

其他办公电脑通过浏览器访问 **A 的 `PUBLIC_URL`** 即可使用全部 Web 功能（上传、SQL、BLOB 迁移等）。

---

## 快速开始

```bash
git clone -b deploy/machine-a https://github.com/luoshirui-192/image.git
cd image

cp .env.app.example .env
# 编辑 .env：PUBLIC_URL、DB_HOST、MYSQL_PASSWORD、SECRET_KEY 等

# 挂载机器 B 的 upload（见下文「NFS 挂载」）
sudo mount -t nfs 192.168.1.20:/data/image_db/upload ./upload

chmod +x start-app.sh
./start-app.sh
```

浏览器打开 `.env` 里的 `PUBLIC_URL`，默认账号 **admin / admin123**（需机器 B 已导入种子数据）。

---

## 前置条件：机器 B 必须先就绪

在部署 A 之前，**机器 B** 需完成：

1. **MySQL 8.0** 已安装并监听内网
2. **数据库已初始化**（在 B 上或任意能连 B 的客户端执行）：

```bash
mysql -h <B_IP> -u root -p < sql/image_db.sql
mysql -h <B_IP> -u root -p image_db < sql/optimize_indexes.sql
mysql -h <B_IP> -u root -p image_db < sql/fix_mysql57_triggers.sql
mysql -h <B_IP> -u root -p image_db < sql/seed_test_data.sql
mysql -h <B_IP> -u root -p image_db < sql/blob_migration.sql
```

3. **应用账号**（允许 A 连接）：

```sql
CREATE USER 'image_db'@'192.168.1.10' IDENTIFIED BY '你的密码';
GRANT ALL ON image_db.* TO 'image_db'@'192.168.1.10';
FLUSH PRIVILEGES;
```

将 `192.168.1.10` 换成 **机器 A 的 IP**。

4. **图片目录 + NFS**：

```bash
sudo mkdir -p /data/image_db/upload
# /etc/exports 示例（仅允许 A）：
# /data/image_db/upload  192.168.1.10(rw,sync,no_subtree_check,no_root_squash)
sudo exportfs -ra
```

5. **防火墙**：B 上对 **A 的 IP** 开放 **3306**（MySQL）、**2049**（NFS）。

> 机器 B **不需要**安装 Docker 或 clone 本仓库（仅需 `sql/` 脚本初始化库）。

---

## 机器 A 环境要求

- Linux（推荐 Ubuntu 22.04 / Debian 12）或 Windows + Docker Desktop
- Git、Docker Engine、Docker Compose 插件
- 4GB+ 内存（首次构建前端镜像）
- 项目路径建议 **纯英文**（Windows Docker 限制）
- 能访问 B 的 **3306** 与 **NFS**

---

## 配置 `.env`

```bash
cp .env.app.example .env
```

| 变量 | 说明 | 示例 |
|------|------|------|
| `PUBLIC_URL` | **A** 的访问地址 | `http://192.168.1.10` |
| `HTTP_PORT` | A 对外端口 | `80` |
| `DB_HOST` | **B** 的 MySQL IP | `192.168.1.20` |
| `DB_PORT` | MySQL 端口 | `3306` |
| `MYSQL_DATABASE` | 库名 | `image_db` |
| `MYSQL_USER` | 库用户 | `image_db` |
| `MYSQL_PASSWORD` | 库密码（与 B 上一致） | 强密码 |
| `SECRET_KEY` | Django 密钥 | `python3 scripts/generate_secret_key.py` |
| `IMAGE_ACCESS_SECRET` | 图片令牌密钥 | 再生成一段 |

`ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS` 由 `docker/set-env.py` 根据 `PUBLIC_URL` **自动写入**，无需手写。

**不要**把 `DB_HOST` 设为 `db`、`localhost`（除非 MySQL 真的在 A 本机——那样请用 `main` 分支的单机 compose）。

---

## NFS 挂载 upload

Backend 将 `./upload` 映射为容器内 `/app/upload`，**生产环境此目录应对应 B 上的真实存储**。

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
| MySQL 容器 | ✅ 本地 `db` 服务 | ❌ 连远程 `DB_HOST` |
| upload | 本地目录 | **NFS 来自 B** |
| 适用场景 | 一台机器.all-in-one | A 应用 + B 数据 |

---

## 功能说明

在 A 的 Web 上可完成与单机相同的业务操作：

- 上传、SQL 查询、BLOB 迁移、BLOB 表视图、分类管理
- 连接**外部旧库**迁 BLOB：由 **A 的 backend 容器**发起连接，旧库需允许 **A 的 IP** 访问
- 数据与文件最终写入 **B 的主库** 与 **B 的 upload**

缩略图缓存 `thumb_cache` 在 A 本地 Docker 卷，丢失可自动重建。

---

## 故障排查

| 现象 | 处理 |
|------|------|
| `DB_HOST 必须设为机器 B` | 编辑 `.env`，`DB_HOST` 填 B 的内网 IP |
| backend 一直 waiting for MySQL | 检查 B 的 MySQL 是否启动；A 能否 `telnet B_IP 3306`；用户是否授权给 A 的 IP |
| 上传/预览失败 | 检查 NFS 是否挂载到 `./upload`；B 上目录权限 |
| 502 | `docker compose -f docker-compose.app.yml logs backend` |
| 登录失败 | 确认 B 上已执行 `seed_test_data.sql`；或 A 首次启动后 backend 已 migrate 成功 |
| 连旧库失败 | 旧库防火墙放行 **A 的 IP**，不是 B |

**测试 A → B 数据库：**

```bash
docker compose -f docker-compose.app.yml exec backend \
  python -c "import django; django.setup(); from django.db import connection; connection.ensure_connection(); print('ok')"
```

---

## 文件清单（机器 A 专用）

| 文件 | 用途 |
|------|------|
| `docker-compose.app.yml` | 仅 web / backend / scheduler |
| `.env.app.example` | 环境变量模板 |
| `start-app.sh` / `start-app.ps1` | 一键启动 |
| `README-MACHINE-A.md` | 本文档 |

---

## 相关链接

- 单机 all-in-one 部署：仓库 `main` 分支 [README.md](README.md)
- 仓库地址：https://github.com/luoshirui-192/image.git
- 分支：`deploy/machine-a`
