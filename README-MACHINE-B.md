# 机器 B 部署指南（图片存储层）

本分支用于 **双机部署** 中的 **机器 B**：**仅负责图片文件存储**，通过 **NFS** 供机器 A 读写 `upload/`。

| 机器 | 职责 |
|------|------|
| **B（本机）** | 大容量磁盘、`upload/` 目录、NFS 导出 |
| **A（服务机）** | MySQL + Docker Web/Backend，挂载 B 的 NFS |

机器 B **不需要** MySQL、Docker 应用或对外 HTTP。也 **不需要** 跑 `start.sh`（单机版）。

数据库与服务端部署见分支 **[deploy/machine-a](https://github.com/luoshirui-192/image/tree/deploy/machine-a)** 与 [README-MACHINE-A.md](https://github.com/luoshirui-192/image/blob/deploy/machine-a/README-MACHINE-A.md)。

---

## 架构

```
用户浏览器
     │
     ▼
机器 A（服务）                    机器 B（本机，仅存储）
┌─────────────────────┐          ┌──────────────────┐
│ web / backend       │          │ /data/.../upload │
│ MySQL (Docker)      │── NFS ──►│ NFS 导出         │
└─────────────────────┘          └──────────────────┘
```

---

## 快速开始（Linux，推荐）

```bash
git clone -b deploy/machine-b https://github.com/luoshirui-192/image.git
cd image

cp .env.storage.example .env
# 编辑：DATA_UPLOAD_ROOT、MACHINE_A_HOSTS（A 的 IP）

chmod +x start-storage.sh scripts/setup-nfs-export.sh
./start-storage.sh
```

完成后告知机器 A 管理员 NFS 挂载信息：

```bash
# 在 A 上执行（IP 与路径按 B 的 .env 填写）
sudo mkdir -p /opt/image_db/upload
sudo mount -t nfs 192.168.1.20:/data/image_db/upload /opt/image_db/upload
```

---

## 环境要求

| 项目 | 建议 |
|------|------|
| 操作系统 | **Linux**（Ubuntu 22.04 / Debian 12）；NFS 服务端需 Linux |
| CPU / 内存 | 1 核、1GB+ 即可（无数据库与应用） |
| 磁盘 | **大容量数据盘** 专存图片 |
| 软件 | Git（可选，仅需脚本时）；`nfs-kernel-server` |
| 网络 | 内网固定 IP；对 **机器 A** 开放 **2049**（NFS） |

> 若 B 为 Windows，需自行配置 SMB/NFS 共享，本仓库脚本面向 Linux NFS。

---

## 配置 `.env`

```bash
cp .env.storage.example .env
```

| 变量 | 说明 | 示例 |
|------|------|------|
| `DATA_UPLOAD_ROOT` | 宿主机图片目录 | `/data/image_db/upload` |
| `NFS_EXPORT_PATH` | NFS 导出路径（通常同上） | `/data/image_db/upload` |
| `MACHINE_A_HOSTS` | 机器 A 的 IP（可多个，空格分隔） | `192.168.1.10` |

---

## 分步部署

### 1. 创建图片目录

```bash
sudo mkdir -p /data/image_db/upload
sudo chmod 1777 /data/image_db/upload
```

或在 `.env` 中修改 `DATA_UPLOAD_ROOT` 后运行 `./start-storage.sh` 自动创建。

### 2. 配置 NFS 导出

```bash
./scripts/setup-nfs-export.sh
```

脚本会写入 `/etc/exports` 并重启 `nfs-server`。

手工配置示例（`/etc/exports`）：

```
/data/image_db/upload  192.168.1.10(rw,sync,no_subtree_check,no_root_squash)
```

```bash
sudo exportfs -ra
sudo systemctl restart nfs-server
```

### 3. 防火墙（仅放行 A）

```bash
# UFW 示例（B 上）
sudo ufw allow from 192.168.1.10 to any port 2049
```

**不要**对公网开放 NFS。

### 4. 机器 A 挂载验证

在 A 上：

```bash
sudo mount -t nfs 192.168.1.20:/data/image_db/upload /opt/image_db/upload
touch /opt/image_db/upload/.nfs_test && rm /opt/image_db/upload/.nfs_test
```

在 B 上应能看到测试文件曾出现。

**开机自动挂载**（A 的 `/etc/fstab`）：

```
192.168.1.20:/data/image_db/upload  /opt/image_db/upload  nfs  defaults,_netdev  0  0
```

---

## 调整 upload 目录位置

1. 编辑 B 的 `.env`：`DATA_UPLOAD_ROOT` 与 `NFS_EXPORT_PATH`
2. 创建新目录并迁移旧数据：`rsync -a 旧路径/ 新路径/`
3. 重新运行 `./scripts/setup-nfs-export.sh`
4. 在 A 上重新挂载新 NFS 路径

数据库在 A 上，改 B 的磁盘路径 **无需改库**（库中存的是相对路径）。

---

## 备份

```bash
tar czf upload_$(date +%F).tar.gz -C /data/image_db upload
# 或按 DATA_UPLOAD_ROOT 实际路径
tar czf upload_$(date +%F).tar.gz -C "$(dirname /data/image_db/upload)" "$(basename /data/image_db/upload)"
```

建议定期备份到独立存储。

---

## 故障排查

| 现象 | 处理 |
|------|------|
| A 上传失败 | A 是否已挂载 NFS；B 上 `exportfs -v`；目录权限 |
| A 挂载失败 | B 防火墙 2049；`MACHINE_A_HOSTS` 是否含 A 的 IP |
| NFS 权限 denied | exports 使用 `no_root_squash`；A 容器以 root 写文件 |
| 改路径后旧图不可见 | A 是否仍挂旧路径；数据是否已 rsync 到新目录 |

---

## 本分支专用文件

| 文件 | 用途 |
|------|------|
| `.env.storage.example` | 环境变量模板 |
| `start-storage.sh` / `start-storage.ps1` | 一键创建目录并配置 NFS |
| `scripts/setup-nfs-export.sh` | 写入 `/etc/exports` |
| `README-MACHINE-B.md` | 本文档 |

---

## 相关链接

- 机器 A 部署：[deploy/machine-a](https://github.com/luoshirui-192/image/tree/deploy/machine-a)
- 单机 all-in-one：`main` 分支 [README.md](README.md)
- 仓库：https://github.com/luoshirui-192/image.git
