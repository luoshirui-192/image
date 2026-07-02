#!/usr/bin/env python3
"""
步骤 30 — 从 .sql.gz 恢复 MySQL（灾难恢复用，请谨慎执行）。

用法：
  python scripts/restore_mysql.py backups/mysql/image_db_20260630_120000.sql.gz
  python scripts/restore_mysql.py backup.sql.gz --dry-run
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ENV = PROJECT_ROOT / "backend" / ".env"


def _load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip()
    return data


def get_db_config(env: dict[str, str]) -> dict[str, str]:
    if env.get("DB_ENGINE", "mysql").lower() != "mysql":
        raise RuntimeError("恢复仅支持 DB_ENGINE=mysql")
    return {
        "host": env.get("DB_HOST", "127.0.0.1"),
        "port": env.get("DB_PORT", "3306"),
        "user": env.get("DB_USER", "root"),
        "password": env.get("DB_PASSWORD", ""),
        "name": env.get("DB_NAME", "image_db"),
    }


def build_mysql_cmd(cfg: dict[str, str], mysql_bin: str) -> list[str]:
    return [
        mysql_bin,
        f"--host={cfg['host']}",
        f"--port={cfg['port']}",
        f"--user={cfg['user']}",
        "--default-character-set=utf8",
        cfg["name"],
    ]


def restore(archive: Path, *, dry_run: bool, mysql_bin: str | None) -> None:
    if not archive.is_file():
        raise RuntimeError(f"备份文件不存在: {archive}")

    cfg = get_db_config(_load_env(BACKEND_ENV))
    mysql = mysql_bin or shutil.which("mysql")
    if not mysql:
        raise RuntimeError("未找到 mysql 客户端")

    cmd = build_mysql_cmd(cfg, mysql)
    print(f"目标库: {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['name']}")
    print(f"来源: {archive}")

    if dry_run:
        print("[dry-run] gunzip -c", archive, "|", " ".join(cmd))
        return

    env_vars = os.environ.copy()
    if cfg["password"]:
        env_vars["MYSQL_PWD"] = cfg["password"]

    opener = gzip.open if archive.suffix == ".gz" or archive.name.endswith(".sql.gz") else open
    with opener(archive, "rb") as src:
        proc = subprocess.run(
            cmd,
            stdin=src,
            stderr=subprocess.PIPE,
            env=env_vars,
            check=False,
        )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"mysql 恢复失败 (exit {proc.returncode}): {err}")
    print("[OK] 数据库恢复完成")


def main() -> int:
    parser = argparse.ArgumentParser(description="从 mysqldump 备份恢复 MySQL")
    parser.add_argument("archive", type=Path, help=".sql.gz 备份文件")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mysql", default="", help="mysql 可执行文件路径")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认覆盖当前库（未指定时仅 dry-run 提示）",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.yes:
        print("恢复将覆盖现有数据。请加 --yes 确认，或先用 --dry-run 查看命令。", file=sys.stderr)
        return 1

    try:
        restore(args.archive, dry_run=args.dry_run, mysql_bin=args.mysql or None)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
