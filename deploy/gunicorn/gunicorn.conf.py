"""Gunicorn 生产配置（步骤 29）。

用法（在 backend 目录或项目根）：
  gunicorn -c deploy/gunicorn/gunicorn.conf.py config.wsgi:application

环境变量（可选，见 deploy/paths.env.example）：
  GUNICORN_BIND、GUNICORN_WORKERS、GUNICORN_TIMEOUT、GUNICORN_LOG_LEVEL
"""
from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

_GUNICORN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _GUNICORN_DIR.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
LOG_DIR = BACKEND_DIR / "logs"

bind = os.getenv("GUNICORN_BIND", os.getenv("BACKEND_UPSTREAM", "127.0.0.1:8000"))
backlog = 2048

# Small-office default (~4–5 concurrent browsers):
# Cap workers so dual-socket hosts do not spawn dozens of processes and exhaust MySQL.
_cpus = multiprocessing.cpu_count() or 2
_default_workers = min(6, max(4, _cpus))
workers = int(os.getenv("GUNICORN_WORKERS", str(_default_workers)))
worker_class = "sync"
threads = 1
worker_connections = 1000
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5

chdir = str(BACKEND_DIR)
wsgi_app = "config.wsgi:application"

LOG_DIR.mkdir(parents=True, exist_ok=True)
accesslog = os.getenv("GUNICORN_ACCESS_LOG", str(LOG_DIR / "gunicorn_access.log"))
errorlog = os.getenv("GUNICORN_ERROR_LOG", str(LOG_DIR / "gunicorn_error.log"))
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = (
    '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
)

proc_name = "image_db"
daemon = False
preload_app = True
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "50"))
