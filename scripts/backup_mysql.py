#!/usr/bin/env python3
"""
步骤 30 — 从 backend/.env 读取 MySQL 连接并执行 mysqldump。

用法：
  python scripts/backup_mysql.py
  python scripts/backup_mysql.py --dry-run
  python scripts/backup_mysql.py --output-dir /opt/image_db/backups/mysql
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ENV = PROJECT_ROOT / "backend" / ".env"
DEFAULT_BACKUP_ROOT = PROJECT_ROOT / "backups"


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
    engine = env.get("DB_ENGINE", "mysql").lower()
    if engine != "mysql":
        raise RuntimeError(f"备份仅支持 DB_ENGINE=mysql，当前为 {engine!r}")
    return {
        "host": env.get("DB_HOST", "127.0.0.1"),
        "port": env.get("DB_PORT", "3306"),
        "user": env.get("DB_USER", "root"),
        "password": env.get("DB_PASSWORD", ""),
        "name": env.get("DB_NAME", "image_db"),
    }


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def build_mysqldump_cmd(cfg: dict[str, str], mysqldump: str) -> list[str]:
    return [
        mysqldump,
        f"--host={cfg['host']}",
        f"--port={cfg['port']}",
        f"--user={cfg['user']}",
        "--single-transaction",
        "--routines",
        "--triggers",
        "--default-character-set=utf8",
        cfg["name"],
    ]


def prune_old_backups(directory: Path, retention_days: int) -> int:
    if retention_days <= 0 or not directory.is_dir():
        return 0
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for path in directory.glob("image_db_*.sql.gz"):
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
            print(f"已删除过期备份: {path.name}")
    return removed


def run_backup(
    *,
    output_dir: Path,
    retention_days: int,
    dry_run: bool,
    mysqldump_bin: str | None,
) -> Path:
    env = _load_env(BACKEND_ENV)
    cfg = get_db_config(env)

    mysqldump = mysqldump_bin or shutil.which("mysqldump")
    if not mysqldump:
        if dry_run:
            mysqldump = "mysqldump"
        else:
            raise RuntimeError("未找到 mysqldump，请安装 MySQL 客户端并加入 PATH")

    output_dir.mkdir(parents=True, exist_ok=True)
    outfile = output_dir / f"image_db_{_timestamp()}.sql.gz"
    cmd = build_mysqldump_cmd(cfg, mysqldump)

    print(f"数据库: {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['name']}")
    print(f"输出: {outfile}")

    if dry_run:
        print("[dry-run]", " ".join(cmd), "> gzip >", outfile)
        return outfile

    env_vars = os.environ.copy()
    if cfg["password"]:
        env_vars["MYSQL_PWD"] = cfg["password"]

    with gzip.open(outfile, "wb") as gz:
        proc = subprocess.run(
            cmd,
            stdout=gz,
            stderr=subprocess.PIPE,
            env=env_vars,
            check=False,
        )
    if proc.returncode != 0:
        outfile.unlink(missing_ok=True)
        err = proc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"mysqldump 失败 (exit {proc.returncode}): {err}")

    size_kb = outfile.stat().st_size / 1024
    print(f"[OK] MySQL 备份完成 ({size_kb:.1f} KB): {outfile}")

    removed = prune_old_backups(output_dir, retention_days)
    if removed:
        print(f"已清理 {removed} 个过期备份（保留 {retention_days} 天）")
    return outfile


def main() -> int:
    parser = argparse.ArgumentParser(description="MySQL 逻辑备份 (mysqldump)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_BACKUP_ROOT / "mysql",
    )
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mysqldump", default="", help="mysqldump 可执行文件路径")
    args = parser.parse_args()

    try:
        run_backup(
            output_dir=args.output_dir,
            retention_days=args.retention_days,
            dry_run=args.dry_run,
            mysqldump_bin=args.mysqldump or None,
        )
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
