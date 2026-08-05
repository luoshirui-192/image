#!/usr/bin/env python3
"""Standalone folder → MinIO (+ optional MySQL path insert).

不依赖 Django / image_db Web 平台。任意机器只需：
  pip install minio pymysql
  （可选）pip install Pillow   # 用于读写宽高，没有则宽高写 0

示例（只上传 MinIO，不写库）：
  python scripts/standalone_ingest_folder_minio.py /data/photos --no-db \\
    --endpoint http://192.168.9.9:9000 --access-key XXX --secret-key YYY \\
    --bucket biox --prefix data/image_db

示例（上传 MinIO + 写入 image_info，方便以后被平台读到）：
  python scripts/standalone_ingest_folder_minio.py /data/photos \\
    --endpoint http://192.168.9.9:9000 --access-key XXX --secret-key YYY \\
    --bucket biox --prefix data/image_db \\
    --db-host 192.168.1.33 --db-port 3306 --db-name image_db \\
    --db-user root --db-password '***' --upload-user admin --category-id 1
"""
from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_EXT = frozenset({"jpg", "jpeg", "png", "gif", "webp", "bmp"})


@dataclass
class Stats:
    found: int = 0
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0


def _norm_suffix(name: str) -> str:
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def _parse_endpoint(endpoint: str, secure_flag: bool) -> tuple[str, bool]:
    raw = (endpoint or "").strip()
    if not raw:
        raise SystemExit("必须提供 --endpoint 或环境变量 MINIO_ENDPOINT")
    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.hostname or ""
        port = parsed.port
        use_ssl = parsed.scheme == "https"
        if not host:
            raise SystemExit(f"MINIO endpoint 无效: {endpoint}")
        if port:
            return f"{host}:{port}", use_ssl
        return host, use_ssl
    return raw, secure_flag


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_dimensions(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return 0, 0
    try:
        with Image.open(BytesIO(data)) as im:
            return int(im.width), int(im.height)
    except Exception:
        return 0, 0


def iter_images(root: Path, *, recursive: bool) -> list[Path]:
    if not root.is_dir():
        raise SystemExit(f"不是目录: {root}")
    it = root.rglob("*") if recursive else root.iterdir()
    out: list[Path] = []
    for p in it:
        if p.is_file() and _norm_suffix(p.name) in ALLOWED_EXT:
            out.append(p)
    return sorted(out, key=lambda x: str(x).lower())


def build_relative_path(category_id: int, suffix: str, when: datetime) -> str:
    date_str = when.astimezone().strftime("%Y%m%d")
    return f"upload/{date_str}/{category_id}/{uuid.uuid4()}.{suffix}"


def make_minio_client(args: argparse.Namespace):
    from minio import Minio

    endpoint, secure = _parse_endpoint(args.endpoint, args.secure)
    return Minio(
        endpoint,
        access_key=args.access_key,
        secret_key=args.secret_key,
        secure=secure,
    )


def connect_db(args: argparse.Namespace):
    import pymysql

    return pymysql.connect(
        host=args.db_host,
        port=int(args.db_port),
        user=args.db_user,
        password=args.db_password or "",
        database=args.db_name,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=10,
    )


def db_has_hash(conn, file_hash: str, image_name: str) -> tuple[bool, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, image_path FROM image_info "
            "WHERE is_delete=0 AND (file_hash=%s OR image_name=%s) LIMIT 1",
            (file_hash, image_name),
        )
        row = cur.fetchone()
    if not row:
        return False, ""
    return True, row[1] or ""


def db_insert_image_info(
    conn,
    *,
    image_name: str,
    image_path: str,
    width: int,
    height: int,
    file_size: int,
    suffix: str,
    file_hash: str,
    upload_user: str,
    category_id: int | None,
    tags: str,
) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO image_info (
              image_name, image_path, image_width, image_height,
              file_size, file_suffix, file_hash, upload_time, update_time,
              upload_user, is_delete, category_id, tags
            ) VALUES (
              %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s
            )
            """,
            (
                image_name,
                image_path,
                width,
                height,
                file_size,
                suffix,
                file_hash,
                now,
                now,
                upload_user,
                category_id,
                tags,
            ),
        )
        return int(cur.lastrowid)


def load_dotenv_simple(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        os.environ.setdefault(key, val)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="独立脚本：遍历文件夹图片 → MinIO；可选写入 MySQL image_info（无需 Django）",
    )
    p.add_argument("root", help="本地图片文件夹")
    p.add_argument("--env-file", default="", help="可选 .env 路径（读取 MINIO_*/DB_*）")
    p.add_argument("--endpoint", default=os.getenv("MINIO_ENDPOINT", ""), help="MinIO endpoint")
    p.add_argument("--access-key", default=os.getenv("MINIO_ACCESS_KEY", ""))
    p.add_argument("--secret-key", default=os.getenv("MINIO_SECRET_KEY", ""))
    p.add_argument("--bucket", default=os.getenv("MINIO_BUCKET", "biox"))
    p.add_argument("--prefix", default=os.getenv("MINIO_PREFIX", "data/image_db"))
    p.add_argument(
        "--secure",
        action="store_true",
        default=os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes", "on"},
    )
    p.add_argument("--no-db", action="store_true", help="只上传 MinIO，不写数据库")
    p.add_argument("--db-host", default=os.getenv("DB_HOST", ""))
    p.add_argument("--db-port", default=os.getenv("DB_PORT", "3306"))
    p.add_argument("--db-name", default=os.getenv("DB_NAME", "image_db"))
    p.add_argument("--db-user", default=os.getenv("DB_USER", ""))
    p.add_argument("--db-password", default=os.getenv("DB_PASSWORD", ""))
    p.add_argument("--upload-user", default="standalone_ingest")
    p.add_argument("--category-id", type=int, default=1)
    p.add_argument("--tags", default="standalone_ingest")
    p.add_argument("--no-recursive", action="store_true")
    p.add_argument("--skip-existing", action="store_true", default=True)
    p.add_argument("--no-skip-existing", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    # pre-parse env-file
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env-file", default="")
    pre_args, _ = pre.parse_known_args(argv)
    if pre_args.env_file:
        load_dotenv_simple(Path(pre_args.env_file))
    else:
        # project-root .env if present
        here = Path(__file__).resolve().parent.parent
        load_dotenv_simple(here / ".env")

    args = build_parser().parse_args(argv)
    # re-bind from env after dotenv
    args.endpoint = args.endpoint or os.getenv("MINIO_ENDPOINT", "")
    args.access_key = args.access_key or os.getenv("MINIO_ACCESS_KEY", "")
    args.secret_key = args.secret_key or os.getenv("MINIO_SECRET_KEY", "")
    args.bucket = args.bucket or os.getenv("MINIO_BUCKET", "biox")
    args.prefix = args.prefix or os.getenv("MINIO_PREFIX", "data/image_db")
    if not args.db_host:
        args.db_host = os.getenv("DB_HOST", "")
    if not args.db_user:
        args.db_user = os.getenv("DB_USER", "")
    if not args.db_password:
        args.db_password = os.getenv("DB_PASSWORD", "")

    if not args.access_key or not args.secret_key:
        raise SystemExit("缺少 MinIO 密钥：--access-key / --secret-key 或 MINIO_ACCESS_KEY/SECRET")

    skip_existing = not args.no_skip_existing
    root = Path(args.root).expanduser().resolve()
    files = iter_images(root, recursive=not args.no_recursive)
    if args.limit and args.limit > 0:
        files = files[: args.limit]

    stats = Stats(found=len(files))
    print(
        f"root={root} found={stats.found} bucket={args.bucket} "
        f"prefix={args.prefix} db={'off' if args.no_db else args.db_host}/{args.db_name} "
        f"dry_run={args.dry_run}"
    )
    if not files:
        print("没有找到图片")
        return 0

    client = None if args.dry_run else make_minio_client(args)
    conn = None
    if not args.no_db and not args.dry_run:
        if not args.db_host or not args.db_user:
            raise SystemExit("写库需要 --db-host/--db-user（或 --no-db 只上传）")
        conn = connect_db(args)

    prefix = (args.prefix or "").strip().strip("/")

    for path in files:
        rel = str(path.relative_to(root))
        try:
            data = path.read_bytes()
            suffix = _norm_suffix(path.name) or "bin"
            file_hash = _sha256(data)
            when = datetime.now(timezone.utc)
            relative_path = build_relative_path(args.category_id, suffix, when)
            object_key = f"{prefix}/{relative_path}" if prefix else relative_path

            if args.dry_run:
                stats.uploaded += 1
                if args.verbose:
                    print(f"  [DRY] {rel} -> {object_key}")
                continue

            if conn is not None and skip_existing:
                exists, existing_path = db_has_hash(conn, file_hash, path.name)
                if exists:
                    stats.skipped += 1
                    if args.verbose:
                        print(f"  [SKIP] {rel} already {existing_path}")
                    continue

            assert client is not None
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            client.put_object(
                args.bucket,
                object_key,
                BytesIO(data),
                length=len(data),
                content_type=content_type,
            )

            if conn is not None:
                width, height = _read_dimensions(data)
                row_id = db_insert_image_info(
                    conn,
                    image_name=path.name,
                    image_path=relative_path,
                    width=width,
                    height=height,
                    file_size=len(data),
                    suffix=suffix,
                    file_hash=file_hash,
                    upload_user=args.upload_user,
                    category_id=args.category_id,
                    tags=(args.tags or "")[:500],
                )
                if args.verbose:
                    print(f"  [OK] {rel} -> {relative_path} (id={row_id})")
            else:
                if args.verbose:
                    print(f"  [OK] {rel} -> s3://{args.bucket}/{object_key}")

            stats.uploaded += 1
        except Exception as exc:
            stats.failed += 1
            print(f"  [FAIL] {rel}: {exc}", file=sys.stderr)

    if conn is not None:
        conn.close()

    print(
        f"done: found={stats.found} uploaded={stats.uploaded} "
        f"skipped={stats.skipped} failed={stats.failed}"
    )
    return 1 if stats.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
