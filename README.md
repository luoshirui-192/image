# 图像路径式数据库管理系统



图片元数据 + 路径存储 + Web SQL 自定义查询面板。



## 最快上手（推荐：Docker）



**从 GitHub 下载后两条命令即可使用**（需先安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)）：



```powershell

# Windows

git clone <你的仓库地址>

cd 图像路径式数据库管理系统

.\start.ps1

```



```bash

# Linux / macOS

git clone <你的仓库地址>

cd 图像路径式数据库管理系统

chmod +x start.sh && ./start.sh

```



浏览器打开 http://localhost ，默认账号 **admin / admin123**。



局域网部署：编辑 `.env` 中的 `PUBLIC_URL=http://服务器IP` 后重新运行 `start.ps1`。



详细说明：[docs/quickstart-docker.md](docs/quickstart-docker.md)

**服务器完整部署**：[服务器部署完整指南.md](服务器部署完整指南.md)

发布到 GitHub：见 [docs/github.md](docs/github.md)



---



## 项目结构



```

├── backend/          # Django + DRF 后端

├── frontend/         # Vue 3 前端

├── upload/           # 图片分层存储目录

├── sql/              # MySQL 建库与种子脚本

├── docker/           # Docker 一键部署配置

├── docker-compose.yml

├── start.ps1 / start.sh

├── deploy/           # 裸机 Nginx + Gunicorn 配置（可选）

└── scripts/          # 辅助脚本

```



## 开发模式（写代码时用）



### 1. 数据库



```bash

mysql -h192.168.1.154 -P3306 -u用户名 -p < sql/image_db.sql

mysql -h192.168.1.154 -P3306 -u用户名 -p image_db < sql/optimize_indexes.sql

mysql -h192.168.1.154 -P3306 -u用户名 -p image_db < sql/seed_test_data.sql

```



### 2. 后端



```bash

cd backend

pip install -r requirements.txt

copy .env.example .env

python manage.py migrate

python manage.py runserver 0.0.0.0:8000

```



### 3. 前端



```bash

cd frontend

npm install

npm run dev

```



访问 http://localhost:5173



## 裸机生产部署（不用 Docker 时）



详见 [docs/deploy.md](docs/deploy.md)（Nginx + Gunicorn + MySQL，步骤 27~30）。



## 技术栈



- 后端：Django 5 + DRF + SimpleJWT + MySQL

- 前端：Vue 3 + Vite + Element Plus + Pinia

- 存储：本地 `upload/YYYYMMDD/category_id/uuid.ext`

- 一键运行：Docker Compose（MySQL + Gunicorn + Nginx）

