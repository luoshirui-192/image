#!/usr/bin/env python3
"""
步骤 30 — 一键备份：MySQL + upload/。

用法：
  python scripts/backup_all.py
  python scripts/backup_all.py --dry-run
  python scripts/backup_all.py --mysql-only
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKUP_ROOT = PROJECT_ROOT / "backups"
PATHS_ENV = PROJECT_ROOT / "deploy" / "paths.env"


def _load_paths_retention() -> int:
    if not PATHS_ENV.is_file():
        return 14
    for line in PATHS_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("BACKUP_RETENTION_DAYS="):
            try:
                return int(line.split("=", 1)[1].strip())
            except ValueError:
                break
    return 14


def _load_backup_root() -> Path:
    if not PATHS_ENV.is_file():
        return DEFAULT_BACKUP_ROOT
    for line in PATHS_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("BACKUP_ROOT="):
            value = line.split("=", 1)[1].strip()
            if value:
                return Path(value)
    return DEFAULT_BACKUP_ROOT


def _run_script(name: str, extra: list[str]) -> int:
    script = PROJECT_ROOT / "scripts" / name
    cmd = [sys.executable, str(script), *extra]
    print(f"\n>> {' '.join(cmd)}")
    return subprocess.call(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(description="MySQL + upload 全量备份")
    parser.add_argument("--backup-root", type=Path, default=None)
    parser.add_argument("--retention-days", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mysql-only", action="store_true")
    parser.add_argument("--upload-only", action="store_true")
    args = parser.parse_args()

    if args.mysql_only and args.upload_only:
        print("不能同时指定 --mysql-only 与 --upload-only", file=sys.stderr)
        return 1

    root = args.backup_root or _load_backup_root()
    retention = args.retention_days if args.retention_days is not None else _load_paths_retention()
    dry = ["--dry-run"] if args.dry_run else []

    print(f"备份根目录: {root}，保留 {retention} 天")
    code = 0

    if not args.upload_only:
        code |= _run_script(
            "backup_mysql.py",
            ["--output-dir", str(root / "mysql"), "--retention-days", str(retention), *dry],
        )
    if not args.mysql_only:
        code |= _run_script(
            "backup_upload.py",
            ["--output-dir", str(root / "upload"), "--retention-days", str(retention), *dry],
        )

    if code == 0:
        print("\n[OK] 备份任务完成")
    else:
        print("\n[FAIL] 部分备份失败", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
