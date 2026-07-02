#!/usr/bin/env python3
"""
步骤 27 — 生产环境一键准备

- 初始化 upload / thumb_cache
- 可选：从 .env.production.example 生成 backend/.env
- pip install、migrate
- 前端 npm install + production build

用法（项目根目录）：
  python scripts/prepare_production.py
  python scripts/prepare_production.py --skip-frontend
  python scripts/prepare_production.py --write-env --force-env
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND = PROJECT_ROOT / "backend"
FRONTEND = PROJECT_ROOT / "frontend"


def run(cmd: list[str], *, cwd: Path) -> None:
    print(f"\n>> {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def copy_if_missing(src: Path, dst: Path, *, force: bool) -> None:
    if dst.exists() and not force:
        print(f"skip (exists): {dst}")
        return
    shutil.copyfile(src, dst)
    print(f"written: {dst}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare production environment (step 27)")
    parser.add_argument("--write-env", action="store_true", help="从模板写入 backend/.env 与 frontend/.env.production")
    parser.add_argument("--force-env", action="store_true", help="覆盖已有 env 文件")
    parser.add_argument("--skip-frontend", action="store_true", help="跳过 npm build")
    parser.add_argument("--skip-migrate", action="store_true", help="跳过 django migrate")
    args = parser.parse_args()

    print(f"project root: {PROJECT_ROOT}")

    run([sys.executable, str(PROJECT_ROOT / "scripts" / "init_storage.py")], cwd=PROJECT_ROOT)

    if args.write_env:
        copy_if_missing(
            BACKEND / ".env.production.example",
            BACKEND / ".env",
            force=args.force_env,
        )
        copy_if_missing(
            FRONTEND / ".env.production.example",
            FRONTEND / ".env.production",
            force=args.force_env,
        )
        print("\n请编辑 backend/.env：替换 SECRET_KEY、IMAGE_ACCESS_SECRET、DB_PASSWORD、ALLOWED_HOSTS")
        print("生成密钥: python scripts/generate_secret_key.py")

    run([sys.executable, "-m", "pip", "install", "-r", "requirements-production.txt"], cwd=BACKEND)

    if not args.skip_migrate:
        run([sys.executable, "manage.py", "migrate", "--noinput"], cwd=BACKEND)

    if not args.skip_frontend:
        fe_env = FRONTEND / ".env.production"
        if not fe_env.is_file():
            copy_if_missing(FRONTEND / ".env.production.example", fe_env, force=False)
        npm = shutil.which("npm")
        if not npm:
            print("ERROR: 未找到 npm，请安装 Node.js 或使用 --skip-frontend", file=sys.stderr)
            return 1
        run([npm, "install"], cwd=FRONTEND)
        run([npm, "run", "build"], cwd=FRONTEND)

    print("\n=== 准备完成 ===")
    print("验收: python scripts/verify_production.py")
    print("临时启动 API: cd backend && python manage.py runserver 0.0.0.0:8000")
    print("步骤 28: python scripts/render_nginx_config.py（见 docs/deploy.md）")
    print("步骤 29: python scripts/render_gunicorn_service.py（见 docs/deploy.md）")
    print("步骤 30: python scripts/backup_all.py && python scripts/smoke_test.py --base-url ...")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"\nERROR: command failed with exit {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
