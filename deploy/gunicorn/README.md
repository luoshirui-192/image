# Gunicorn（步骤 29）

## 文件

| 文件 | 说明 |
|------|------|
| `gunicorn.conf.py` | Gunicorn 运行参数（监听、worker、日志） |
| `image_db.service.template` | systemd 单元模板 |
| `generated/image_db.service` | 由 `render_gunicorn_service.py` 生成 |

## 依赖

生产环境安装（含 Gunicorn）：

```bash
cd backend
pip install -r requirements-production.txt
```

**注意：** Gunicorn 仅支持 Linux/macOS，Windows 开发机请继续用 `runserver`；生产在 Linux 服务器运行。

## 手动启动（调试）

```bash
cd /opt/image_db
export GUNICORN_BIND=127.0.0.1:8000
./scripts/run_gunicorn.sh
```

或：

```bash
cd /opt/image_db/backend
../.venv/bin/gunicorn -c ../deploy/gunicorn/gunicorn.conf.py config.wsgi:application
```

验收：`curl http://127.0.0.1:8000/api/health/`

## systemd 安装

```bash
cp deploy/paths.env.example deploy/paths.env
# 编辑 VENV_PATH、RUN_USER、GUNICORN_* 等

python3 scripts/render_gunicorn_service.py
sudo cp deploy/gunicorn/generated/image_db.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now image_db
sudo systemctl status image_db
```

完整说明见 [docs/deploy.md](../../docs/deploy.md) 步骤 29。
