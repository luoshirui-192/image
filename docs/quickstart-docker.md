# Docker 一键部署

从 GitHub 克隆后，**只需 Docker**，无需手工安装 Python、Node、MySQL、Nginx。

## 前提

- 已安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)（Windows/macOS）或 Docker Engine（Linux）
- 机器有 **4GB+ 内存**（首次构建前端镜像需要几分钟）

## 三步启动

```bash
git clone https://github.com/你的用户名/图像路径式数据库管理系统.git
cd 图像路径式数据库管理系统

# Windows PowerShell
.\start.ps1

# Linux / macOS
chmod +x start.sh && ./start.sh
```

首次运行会自动：

1. 复制 `.env.docker.example` → `.env`
2. 构建并启动 MySQL、Django（Gunicorn）、Nginx（含前端）、**定时维护 scheduler**
3. 自动建库、导入 `sql/`、执行 `migrate`

浏览器打开 **http://localhost**（若在别的机器访问，先改 `.env` 里的 `PUBLIC_URL` 再重新 `./start.sh`）。

默认账号：**admin / admin123**

## 修改访问地址（局域网部署）

编辑项目根目录 `.env`：

```env
PUBLIC_URL=http://192.168.1.100
HTTP_PORT=80
SECRET_KEY=换成随机字符串
IMAGE_ACCESS_SECRET=再换一个随机字符串
MYSQL_ROOT_PASSWORD=强密码
MYSQL_PASSWORD=强密码
```

然后重新执行 `start.ps1` 或 `start.sh`（会同步 `ALLOWED_HOSTS` / `CORS`）。

## 常用命令

```bash
docker compose ps          # 查看状态
docker compose logs -f scheduler # 定时维护日志（operate_log 清理等）
docker compose down        # 停止
docker compose down -v     # 停止并清空数据库与上传数据（慎用）
```

## 数据保存在哪

Docker 卷（不会因容器重启丢失）：

| 卷名 | 内容 |
|------|------|
| `mysql_data` | 数据库 |
| `upload_data` | 上传的图片 |
| `thumb_cache` | 缩略图缓存 |

备份仍可使用 `scripts/backup_all.py`（需在容器外挂载卷或进入容器执行）；简单场景可用 `docker compose exec db mysqldump ...`。

## 与「手工部署」的关系

| 方式 | 适合 |
|------|------|
| **Docker（本页）** | 快速试用、内网一键交付、GitHub 下载即用 |
| [deploy.md](deploy.md) 步骤 27~30 | 不用 Docker、要裸机 Nginx+Gunicorn 的生产环境 |

两种方式可以并存：开发用 Docker 试用，正式环境再选手工部署。

## 故障排查

| 现象 | 处理 |
|------|------|
| 构建很慢 | 首次需下载镜像并 `npm ci`，属正常 |
| 502 | `docker compose logs backend` 看是否 migrate 失败 |
| 登录失败 | 等 MySQL 初始化完成（约 1 分钟）后刷新 |
| 端口 80 被占用 | `.env` 里改 `HTTP_PORT=8080`，访问 `http://localhost:8080` |
