# Nginx 配置（步骤 28）

## 文件说明

| 文件 | 说明 |
|------|------|
| `image_db.conf.template` | 站点配置模板 |
| `generated/image_db.conf` | 由 `render_nginx_config.py` 生成，复制到服务器 Nginx |

## 快速生成

```powershell
# 开发机（按本机路径生成，便于检查语法）
copy deploy\paths.env.example deploy\paths.env
# 编辑 deploy\paths.env：PROJECT_ROOT、SERVER_NAME 等

python scripts\render_nginx_config.py
```

生成结果：`deploy/nginx/generated/image_db.conf`

## 安装到 Linux 服务器

```bash
# 1. 安装 Nginx
sudo apt install nginx   # Debian/Ubuntu

# 2. 在服务器上生成配置（PROJECT_ROOT 填服务器实际路径）
cd /opt/image_db
cp deploy/paths.env.example deploy/paths.env
vim deploy/paths.env
python3 scripts/render_nginx_config.py

# 3. 启用站点
sudo cp deploy/nginx/generated/image_db.conf /etc/nginx/sites-available/image_db.conf
sudo ln -sf /etc/nginx/sites-available/image_db.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 验收前临时后端

步骤 29（Gunicorn）完成前，可在服务器上临时启动：

```bash
cd /opt/image_db/backend
source .venv/bin/activate   # 若使用虚拟环境
python manage.py runserver 127.0.0.1:8000
```

再通过浏览器访问 `http://SERVER_NAME/` 与 `http://SERVER_NAME/api/health/`。

完整说明见 [docs/deploy.md](../../docs/deploy.md) 步骤 28。
