#!/usr/bin/env python3
"""
步骤 29 — 启动 Gunicorn（跨平台入口；Gunicorn 本体仅 Linux/macOS）。

用法：
  python scripts/run_gunicorn.py

Windows 上会提示使用 runserver；Linux 上调用 gunicorn。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND = PROJECT_ROOT / "backend"
CONF = PROJECT_ROOT / "deploy/gunicorn/gunicorn.conf.py"


def _load_paths_env() -> None:
    for name in ("paths.env", "paths.env.example"):
        path = PROJECT_ROOT / "deploy" / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            os.environ.setdefault(key, value)
        break


def main() -> int:
    if sys.platform == "win32":
        print("Gunicorn 不支持 Windows，开发请使用:")
        print("  cd backend && python manage.py runserver 127.0.0.1:8000")
        print("生产请在 Linux 服务器执行 scripts/run_gunicorn.sh 或 systemd。")
        return 1

    if not CONF.is_file():
        print(f"ERROR: 缺少 {CONF}", file=sys.stderr)
        return 1

    _load_paths_env()
    bind = os.environ.get("GUNICORN_BIND") or os.environ.get("BACKEND_UPSTREAM", "127.0.0.1:8000")
    os.environ.setdefault("GUNICORN_BIND", bind)

    venv_path = os.environ.get("VENV_PATH", str(PROJECT_ROOT / ".venv"))
    gunicorn = Path(venv_path) / "bin" / "gunicorn"
    if not gunicorn.is_file():
        found = shutil.which("gunicorn")
        if not found:
            print("未找到 gunicorn，请执行: pip install -r backend/requirements-production.txt", file=sys.stderr)
            return 1
        gunicorn = Path(found)

    cmd = [str(gunicorn), "-c", str(CONF), "config.wsgi:application"]
    print(f">> {' '.join(cmd)} (bind={bind})")
    return subprocess.call(cmd, cwd=BACKEND)


if __name__ == "__main__":
    raise SystemExit(main())
