#!/usr/bin/env python3
"""
步骤 30 — 打包 upload/ 目录（图片文件分层存储）。

用法：
  python scripts/backup_upload.py
  python scripts/backup_upload.py --dry-run
"""
from __future__ import annotations

import argparse
import shutil
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


def resolve_upload_root(env: dict[str, str]) -> Path:
    raw = env.get("UPLOAD_ROOT", "").strip()
    if raw:
        return Path(raw)
    return PROJECT_ROOT / "upload"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def prune_old_archives(directory: Path, retention_days: int, prefix: str) -> int:
    if retention_days <= 0 or not directory.is_dir():
        return 0
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for path in directory.glob(f"{prefix}_*.tar.gz"):
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
            print(f"已删除过期备份: {path.name}")
    return removed


def run_backup(
    *,
    upload_root: Path,
    output_dir: Path,
    retention_days: int,
    dry_run: bool,
) -> Path:
    if not upload_root.is_dir():
        raise RuntimeError(f"upload 目录不存在: {upload_root}")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_base = output_dir / f"upload_{_timestamp()}"
    archive_file = Path(f"{archive_base}.tar.gz")

    print(f"源目录: {upload_root}")
    print(f"输出: {archive_file}")

    if dry_run:
        print(f"[dry-run] tar.gz {upload_root} -> {archive_file}")
        return archive_file

    created = shutil.make_archive(
        str(archive_base),
        "gztar",
        root_dir=upload_root.parent,
        base_dir=upload_root.name,
    )
    archive_path = Path(created)
    size_mb = archive_path.stat().st_size / (1024 * 1024)
    print(f"[OK] upload 备份完成 ({size_mb:.2f} MB): {archive_path}")

    removed = prune_old_archives(output_dir, retention_days, "upload")
    if removed:
        print(f"已清理 {removed} 个过期备份（保留 {retention_days} 天）")
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description="upload/ 目录归档备份")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_BACKUP_ROOT / "upload",
        help="备份输出目录",
    )
    parser.add_argument("--upload-root", type=Path, default=None, help="覆盖 UPLOAD_ROOT")
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env = _load_env(BACKEND_ENV)
    upload_root = args.upload_root or resolve_upload_root(env)

    try:
        run_backup(
            upload_root=upload_root,
            output_dir=args.output_dir,
            retention_days=args.retention_days,
            dry_run=args.dry_run,
        )
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
