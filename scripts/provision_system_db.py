#!/usr/bin/env python3
"""
在指定 MySQL 实例上新建独立「系统库」，并把误放进业务库的系统表迁过去。

默认场景（192.168.1.33）:
  - 业务库 / 迁移目标库: ara_fp_analyst  （保留业务表，搬走系统表）
  - 本系统库:            image_db         （新建，存放 image_info / 迁移配置等）

同实例迁移使用 RENAME TABLE（原子、快速，不复制数据）。

示例:
  python scripts/provision_system_db.py ^
    --host 192.168.1.33 --user root --password YOUR_ROOT_PASS

  python scripts/provision_system_db.py --dry-run --host 192.168.1.33 --user root --password xxx
  python scripts/provision_system_db.py --init-only   # 只建空库+跑 SQL，不搬表
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import MySQLdb
except ImportError as exc:
    raise SystemExit("需要 MySQLdb（mysqlclient）。请先: pip install mysqlclient") from exc

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"

# 属于本系统（Django 应用库）的表；不得留在业务库 ara_fp_analyst
APP_TABLES = (
    # 核心业务
    "sys_user",
    "image_category",
    "image_info",
    "operate_log",
    # BLOB / 浏览 / 同步
    "blob_migration_source",
    "image_source_map",
    "external_db_connection",
    "blob_table_view",
    "blob_migration_job",
    "blob_migration_job_error",
    "blob_sync_run",
    # Django
    "django_migrations",
    "django_content_type",
    "django_session",
    "django_admin_log",
    "auth_group",
    "auth_group_permissions",
    "auth_permission",
)

# 建空表用的参考 SQL（CREATE IF NOT EXISTS / 可重复执行部分）
INIT_SQL_FILES = (
    "blob_migration.sql",
    "blob_migration_jobs.sql",
    "blob_sync.sql",
    "optimize_indexes.sql",
    "add_file_hash.sql",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="在主机上新建系统库并从业务库迁出系统表")
    p.add_argument("--host", default="192.168.1.33")
    p.add_argument("--port", type=int, default=3306)
    p.add_argument("--user", default="root")
    p.add_argument("--password", default=os.getenv("MYSQL_ROOT_PASSWORD", ""))
    p.add_argument("--wrong-db", default="ara_fp_analyst", help="误放了系统表的业务库")
    p.add_argument("--system-db", default="image_db", help="新建的本系统库名")
    p.add_argument(
        "--app-user",
        default=os.getenv("MYSQL_USER", "image_db"),
        help="应用账号（会 GRANT 系统库）",
    )
    p.add_argument(
        "--app-password",
        default=os.getenv("MYSQL_PASSWORD", ""),
        help="应用账号密码；空则只 GRANT 不改密码",
    )
    p.add_argument("--init-only", action="store_true", help="只建库+跑 SQL，不从业务库搬表")
    p.add_argument("--dry-run", action="store_true", help="只打印将要执行的操作")
    p.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    return p.parse_args()


def connect(host: str, port: int, user: str, password: str, db: str | None = None):
    kwargs = dict(
        host=host,
        port=port,
        user=user,
        passwd=password or "",
        charset="utf8mb4",
        connect_timeout=20,
    )
    if db:
        kwargs["db"] = db
    try:
        return MySQLdb.connect(**kwargs)
    except MySQLdb.Error as exc:
        raise SystemExit(f"连接失败 {host}:{port}: {exc}") from exc


def quote_ident(name: str) -> str:
    if not name or not all(c.isalnum() or c == "_" for c in name):
        raise SystemExit(f"非法标识符: {name!r}")
    return f"`{name}`"


def list_tables(conn, database: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT TABLE_NAME FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
            """,
            [database],
        )
        return {str(r[0]) for r in cur.fetchall()}


def database_exists(conn, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s LIMIT 1",
            [name],
        )
        return cur.fetchone() is not None


def run_sql_file(conn, path: Path, *, dry_run: bool) -> None:
    if not path.is_file():
        print(f"  [skip] 缺少 SQL 文件: {path}")
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    # 跳过危险 DROP：本脚本只用于补齐，不覆盖已迁入的数据
    statements: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or stripped.startswith("/*") or stripped == "":
            continue
        if stripped.upper().startswith("DROP TABLE"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            buf = []
            if stmt:
                statements.append(stmt)
    if buf:
        stmt = "\n".join(buf).strip().rstrip(";").strip()
        if stmt:
            statements.append(stmt)

    print(f"  执行 {path.name}: {len(statements)} 条语句")
    if dry_run:
        return
    with conn.cursor() as cur:
        for stmt in statements:
            try:
                cur.execute(stmt)
            except MySQLdb.Error as exc:
                # IF NOT EXISTS / 重复索引等可忽略
                msg = str(exc).lower()
                if "already exists" in msg or "duplicate" in msg:
                    continue
                print(f"    warn: {exc} | sql={stmt[:120]}...")
    conn.commit()


def ensure_core_tables_sql() -> str:
    """最小核心表，避免依赖含 DROP/INSERT 的 image_db.sql。"""
    return """
CREATE TABLE IF NOT EXISTS `image_category` (
  `id` int(10) UNSIGNED NOT NULL AUTO_INCREMENT,
  `category_name` varchar(100) NOT NULL DEFAULT '',
  `sort` int(11) NOT NULL DEFAULT 0,
  `create_time` datetime NULL DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE IF NOT EXISTS `sys_user` (
  `id` int(10) UNSIGNED NOT NULL AUTO_INCREMENT,
  `password` varchar(128) NOT NULL,
  `username` varchar(100) NOT NULL,
  `role` varchar(20) NOT NULL DEFAULT 'user',
  `status` smallint NOT NULL DEFAULT 1,
  `create_time` datetime NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE IF NOT EXISTS `image_info` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `image_name` varchar(255) NOT NULL DEFAULT '',
  `image_path` varchar(500) NOT NULL DEFAULT '',
  `image_width` int(11) NOT NULL DEFAULT 0,
  `image_height` int(11) NOT NULL DEFAULT 0,
  `file_size` bigint(20) UNSIGNED NOT NULL DEFAULT 0,
  `file_suffix` varchar(20) NOT NULL DEFAULT '',
  `file_hash` varchar(64) NOT NULL DEFAULT '',
  `upload_time` datetime NOT NULL,
  `update_time` datetime NOT NULL,
  `upload_user` varchar(100) NOT NULL DEFAULT '',
  `is_delete` smallint NOT NULL DEFAULT 0,
  `category_id` int(10) UNSIGNED NULL DEFAULT NULL,
  `tags` varchar(500) NOT NULL DEFAULT '',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE IF NOT EXISTS `operate_log` (
  `id` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id` int(10) UNSIGNED NULL DEFAULT NULL,
  `username` varchar(100) NOT NULL DEFAULT '',
  `action_type` varchar(20) NOT NULL DEFAULT '',
  `sql_content` text NULL,
  `detail` varchar(500) NOT NULL DEFAULT '',
  `ip` varchar(50) NOT NULL DEFAULT '',
  `create_time` datetime NULL DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
"""


def main() -> int:
    args = parse_args()
    if not args.password and not args.dry_run:
        raise SystemExit("请用 --password 或环境变量 MYSQL_ROOT_PASSWORD 提供 root 密码")

    wrong = args.wrong_db
    system = args.system_db
    print("=" * 60)
    print(f"主机:       {args.host}:{args.port}")
    print(f"业务库(误): {wrong}  ← 系统表将迁出，业务表保留")
    print(f"系统库(新): {system}  ← 本应用 Django DB_NAME")
    print(f"模式:       {'DRY-RUN' if args.dry_run else ('仅初始化' if args.init_only else '建库+迁表')}")
    print("=" * 60)

    if not args.yes and not args.dry_run:
        ans = input("确认执行？输入 yes 继续: ").strip().lower()
        if ans != "yes":
            print("已取消")
            return 1

    conn = connect(args.host, args.port, args.user, args.password)
    conn.autocommit(True)

    # 1) create system db
    create_db = (
        f"CREATE DATABASE IF NOT EXISTS {quote_ident(system)} "
        f"DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci"
    )
    print(f"\n[1] 创建系统库 {system}")
    print(f"  SQL: {create_db}")
    if not args.dry_run:
        with conn.cursor() as cur:
            cur.execute(create_db)

    # 2) move tables from wrong db
    moved: list[str] = []
    skipped: list[str] = []
    missing_in_wrong: list[str] = []

    if not args.init_only:
        print(f"\n[2] 从 {wrong} 迁出系统表 → {system}")
        if not database_exists(conn, wrong):
            print(f"  警告: 业务库 {wrong} 不存在，跳过迁表")
        else:
            wrong_tables = list_tables(conn, wrong)
            system_tables = list_tables(conn, system) if database_exists(conn, system) else set()
            for table in APP_TABLES:
                if table not in wrong_tables:
                    missing_in_wrong.append(table)
                    continue
                if table in system_tables:
                    skipped.append(f"{table} (系统库已存在，跳过)")
                    continue
                sql = (
                    f"RENAME TABLE {quote_ident(wrong)}.{quote_ident(table)} "
                    f"TO {quote_ident(system)}.{quote_ident(table)}"
                )
                print(f"  MOVE {wrong}.{table} → {system}.{table}")
                if not args.dry_run:
                    with conn.cursor() as cur:
                        cur.execute(sql)
                moved.append(table)

            leftover_app = sorted(set(APP_TABLES) & wrong_tables - set(moved))
            if leftover_app and not args.dry_run:
                # 目标已有同名时未迁出
                print(f"  仍留在 {wrong} 的系统表名(未迁): {leftover_app}")

            remaining_business = sorted(wrong_tables - set(APP_TABLES))
            print(f"  业务库保留表数: {len(remaining_business)}")
            if remaining_business[:20]:
                print(f"  示例: {', '.join(remaining_business[:20])}")

    # 3) ensure schema for missing tables
    print(f"\n[3] 在 {system} 补齐缺失系统表结构")
    if not args.dry_run:
        conn.select_db(system)
        with conn.cursor() as cur:
            for stmt in ensure_core_tables_sql().split(";"):
                s = stmt.strip()
                if s:
                    try:
                        cur.execute(s)
                    except MySQLdb.Error as exc:
                        if "already exists" not in str(exc).lower():
                            print(f"    warn core: {exc}")
        for fname in INIT_SQL_FILES:
            run_sql_file(conn, SQL_DIR / fname, dry_run=False)
    else:
        for fname in INIT_SQL_FILES:
            print(f"  would run sql/{fname}")

    # 4) grants
    print(f"\n[4] 授权应用用户 {args.app_user} → {system}.*")
    if args.app_user and not args.dry_run:
        user = args.app_user.replace("'", "").replace(";", "")
        with conn.cursor() as cur:
            if args.app_password:
                pwd = args.app_password.replace("'", "").replace("\\", "\\\\")
                for host_pat in ("%", "localhost"):
                    try:
                        cur.execute(
                            f"CREATE USER IF NOT EXISTS '{user}'@'{host_pat}' IDENTIFIED BY '{pwd}'"
                        )
                    except MySQLdb.Error:
                        try:
                            cur.execute(
                                f"CREATE USER '{user}'@'{host_pat}' IDENTIFIED BY '{pwd}'"
                            )
                        except MySQLdb.Error as exc:
                            print(f"    create user @{host_pat} warn: {exc}")
                    try:
                        cur.execute(
                            f"ALTER USER '{user}'@'{host_pat}' IDENTIFIED BY '{pwd}'"
                        )
                    except MySQLdb.Error:
                        pass
            for host_pat in ("%", "localhost"):
                try:
                    cur.execute(
                        f"GRANT ALL PRIVILEGES ON {quote_ident(system)}.* TO '{user}'@'{host_pat}'"
                    )
                except MySQLdb.Error as exc:
                    print(f"    grant @{host_pat} warn: {exc}")
            cur.execute("FLUSH PRIVILEGES")
    elif args.dry_run:
        print(f"  would GRANT ALL ON {system}.* TO {args.app_user}")

    # 5) summary + .env hint
    print("\n" + "=" * 60)
    print("完成摘要")
    print(f"  迁出表: {len(moved)} → {moved}")
    print(f"  跳过:   {skipped}")
    print(f"  业务库本无的系统表名(将靠建表补齐): {[t for t in missing_in_wrong if t in APP_TABLES[:11]]}")
    print()
    print("请立刻把应用系统库指到新库（示例）:")
    print(f"  DB_HOST={args.host}")
    print(f"  DB_PORT={args.port}")
    print(f"  MYSQL_DATABASE={system}")
    print(f"  DB_NAME={system}")
    print(f"  MYSQL_USER={args.app_user}")
    print("  USE_EXTERNAL_MYSQL=1   # 若 Docker 访问宿主机/远端 MySQL")
    print()
    print(f"业务数据 / 导出目标库继续用: {wrong}")
    print("  （在「外部库连接」里 db_name 填 ara_fp_analyst，不要填系统库）")
    print("=" * 60)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
