# 机器 B 部署指南（MinIO 存储层）

本分支用于 **双机部署** 中的 **机器 B**：对接公司 **MinIO 对象存储**（亚略特 AI 框架 VIP `192.168.9.9`），为 image_db 准备 `biox` 桶内的对象前缀与访问账号。

| 机器 | 职责 |
|------|------|
| **B（本机）** | MinIO 租户配置：前缀初始化、权限验证、备份同步（可选） |
| **A（服务机）** | MySQL + Docker Web/Backend，通过 **S3 SDK** 直连 MinIO |

机器 B **不需要** MySQL、Docker 应用、NFS 服务端。也 **不需要** 跑 `start.sh`（单机版）。

数据库与服务端部署见分支 **[deploy/machine-a](https://github.com/luoshirui-192/image/tree/deploy/machine-a)** 与 [README-MACHINE-A.md](https://github.com/luoshirui-192/image/blob/deploy/machine-a/README-MACHINE-A.md)。

---

## 架构

```
用户浏览器
     │
     ▼
机器 A（服务）                         192.168.9.9 MinIO VIP
┌─────────────────────┐   S3 API    ┌──────────────────────────┐
│ web / backend       │────────────►│ biox/data/image_db/      │
│ MySQL (Docker)      │  (9000)     │   upload/YYYYMMDD/...    │
└─────────────────────┘             │        ↓ 101/102 节点      │
                                    └──────────────────────────┘
```

- **9.100** 是对外统一入口（Keepalived + Nginx LB），实际数据在 **9.101 / 9.102**。
- image_db 数据库仍存相对路径 `upload/{date}/{category}/{uuid}.ext`；物理文件在 MinIO 的 `data/image_db/upload/...`。
- 缩略图缓存仍在 **机器 A** 本地 `thumb_cache/`，不写入 MinIO。

---

## 快速开始（Linux，推荐）

```bash
git clone -b deploy/machine-b https://github.com/luoshirui-192/image.git
cd image

cp .env.storage.example .env
# 编辑：MINIO_ACCESS_KEY、MINIO_SECRET_KEY、MACHINE_A_HOSTS

chmod +x scripts/setup-minio-prefix.sh start-storage.sh
./start-storage.sh
```

完成后将 `.env` 中的 MinIO 配置交给 **机器 A** 管理员（或自行部署 A）。

---

## 环境要求

| 项目 | 建议 |
|------|------|
| 操作系统 | Linux / macOS / Windows（仅需 mc 与管理脚本） |
| 软件 | [MinIO Client (`mc`)](https://min.io/docs/minio/linux/reference/minio-mc.html) |
| 网络 | 能访问 **192.168.9.9:9000**（MinIO API） |
| 账号 | 由 MinIO 管理员分配（需对 `biox` 桶有读写权限） |

> MinIO 集群由公司基础设施维护；机器 B 侧只做 **前缀初始化与验证**，不在 9.100 上安装 image_db 应用。

---

## 配置 `.env`

```bash
cp .env.storage.example .env
```

| 变量 | 说明 | 示例 |
|------|------|------|
| `MINIO_ENDPOINT` | MinIO VIP + 端口 | `http://192.168.9.9:9000` |
| `MINIO_ACCESS_KEY` | 访问密钥 | 管理员分配 |
| `MINIO_SECRET_KEY` | 秘密密钥 | 管理员分配 |
| `MINIO_BUCKET` | 桶名 | `biox` |
| `MINIO_PREFIX` | image_db 对象前缀 | `data/image_db` |
| `MINIO_MC_ALIAS` | mc 别名 | `aratek` |
| `MACHINE_A_HOSTS` | 机器 A IP（文档/防火墙参考） | `192.168.17.162` |

---

## MinIO 目录规划

与亚略特 AI 框架 `biox` 桶一致：

| MinIO 路径 | 用途 |
|------------|------|
| `biox/data/image_db/upload/` | image_db 上传图片（对应库表 `image_path`） |
| `biox/data/image_db/backups/` | 可选，定时备份 tar.gz |
| `biox/team/{用户}/` | 个人实验数据（与 image_db 无关时可忽略） |

对象 key 示例：

```
data/image_db/upload/20260706/2/550e8400-e29b-41d4-a716-446655440001.jpg
```

---

## 初始化前缀

```bash
./start-storage.sh
# 或
./scripts/setup-minio-prefix.sh
```

验证读写：

```bash
mc alias set aratek http://192.168.9.9:9000 USER PASS
mc ls aratek/biox/data/image_db/
echo test | mc pipe aratek/biox/data/image_db/upload/.probe
mc rm aratek/biox/data/image_db/upload/.probe
```

---

## 与机器 A 的交接清单

部署 A 前，确认 B 侧已完成：

1. MinIO 账号对 `biox/data/image_db/` 有 **读写删** 权限  
2. **机器 A IP** 可访问 `192.168.9.9:9000`（防火墙/路由）  
3. 已将以下变量写入 A 的 `.env`（见 machine-a 分支 `.env.app.example`）：

```env
STORAGE_BACKEND=minio
MINIO_ENDPOINT=http://192.168.9.9:9000
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
MINIO_BUCKET=biox
MINIO_PREFIX=data/image_db
```

---

## 可选：备份与迁移

从旧 NFS/本地 `upload/` 迁移到 MinIO：

```bash
mc mirror /data/image_db/upload aratek/biox/data/image_db/upload/
```

打包备份（与 `scripts/backup_upload.py` 配合）：

```bash
python scripts/backup_upload.py
mc cp backups/upload_*.tar.gz aratek/biox/data/image_db/backups/
```

---

## 故障排查

| 现象 | 检查 |
|------|------|
| mc 连接失败 | `curl http://192.168.9.9:9000/minio/health/live` |
| Access Denied | 账号策略是否含 `biox/data/image_db/*` |
| A 上传失败 | A 的 `STORAGE_BACKEND=minio`；容器能否访问 9.100:9000 |
| 路径不存在 | key 应为 `data/image_db/upload/...`，不是省略 `upload/` |

---

## 本分支相关文件

| 文件 | 说明 |
|------|------|
| `.env.storage.example` | MinIO 环境变量模板 |
| `scripts/setup-minio-prefix.sh` | 初始化 `biox` 桶内前缀 |
| `start-storage.sh` / `start-storage.ps1` | 一键检查与初始化 |
| `backend/utils/storage.py` | S3/MinIO 存储后端（A 侧运行时使用） |
| `README-MACHINE-B.md` | 本文档 |

---

## 相关链接

- 机器 A 部署：[deploy/machine-a](https://github.com/luoshirui-192/image/tree/deploy/machine-a)
- 单机 Docker 部署：[main 分支 README](https://github.com/luoshirui-192/image/blob/main/README.md)
