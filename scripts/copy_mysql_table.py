#!/usr/bin/env python3
"""
Safely copy a MySQL table between databases (read-only on source).

Handles MySQL 8.0 -> 5.7 collation differences (utf8mb4_0900_ai_ci -> utf8mb4_general_ci).

Examples:
  python scripts/copy_mysql_table.py ^
    --src-host 192.168.17.17 --src-db image_match_system --src-user root --src-password xxx ^
    --dst-host 192.168.1.154 --dst-db image_db --dst-user root --dst-password xxx ^
    --table t_images_SF105

  python scripts/copy_mysql_table.py ... --dry-run
  python scripts/copy_mysql_table.py ... --dst-table t_images_SF105_copy1 --replace-dst
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Any

import MySQLdb
from MySQLdb.cursors import DictCursor

MYSQL8_COLLATIONS = (
    "utf8mb4_0900_ai_ci",
    "utf8mb4_0900_as_ci",
    "utf8mb4_0900_as_cs",
    "utf8mb4_0900_bin",
    "utf8mb4_0900_ai_ci",
)
DEFAULT_TARGET_COLLATION = "utf8mb4_general_ci"
DEFAULT_TARGET_CHARSET = "utf8mb4"
BATCH_SIZE = 20


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy a MySQL table without modifying the source.")
    parser.add_argument("--src-host", required=True)
    parser.add_argument("--src-port", type=int, default=3306)
    parser.add_argument("--src-db", required=True)
    parser.add_argument("--src-user", required=True)
    parser.add_argument("--src-password", default="")
    parser.add_argument("--dst-host", required=True)
    parser.add_argument("--dst-port", type=int, default=3306)
    parser.add_argument("--dst-db", required=True)
    parser.add_argument("--dst-user", required=True)
    parser.add_argument("--dst-password", default="")
    parser.add_argument("--table", required=True, help="Source table name")
    parser.add_argument("--dst-table", default="", help="Target table name (default: same as --table)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--replace-dst", action="store_true", help="DROP target table if it exists")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def connect(
    *,
    host: str,
    port: int,
    db: str,
    user: str,
    password: str,
) -> MySQLdb.Connection:
    try:
        return MySQLdb.connect(
            host=host,
            port=port,
            user=user,
            passwd=password,
            db=db,
            charset="utf8mb4",
            connect_timeout=15,
        )
    except MySQLdb.Error as exc:
        raise SystemExit(f"连接失败 {host}:{port}/{db}: {exc}") from exc


def fetch_version(conn: MySQLdb.Connection) -> str:
    with conn.cursor() as cursor:
        cursor.execute("SELECT VERSION()")
        row = cursor.fetchone()
    return str(row[0] if row else "")


def normalize_create_table(sql: str) -> str:
    result = sql
    for collation in MYSQL8_COLLATIONS:
        result = result.replace(collation, DEFAULT_TARGET_COLLATION)
    result = re.sub(
        r"CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci",
        "",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        r"DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci",
        f"DEFAULT CHARSET={DEFAULT_TARGET_CHARSET} COLLATE={DEFAULT_TARGET_COLLATION}",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        r"CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci",
        f"CHARACTER SET = {DEFAULT_TARGET_CHARSET} COLLATE = {DEFAULT_TARGET_COLLATION}",
        result,
        flags=re.IGNORECASE,
    )
    return result


def table_exists(conn: MySQLdb.Connection, table: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            LIMIT 1
            """,
            (table,),
        )
        return cursor.fetchone() is not None


def get_create_table_sql(conn: MySQLdb.Connection, table: str) -> str:
    with conn.cursor() as cursor:
        cursor.execute(f"SHOW CREATE TABLE `{table}`")
        row = cursor.fetchone()
    if not row or len(row) < 2:
        raise SystemExit(f"源表不存在或无法读取结构: {table}")
    return normalize_create_table(str(row[1]))


def rewrite_create_table_for_target(create_sql: str, *, src_table: str, dst_table: str) -> str:
    result = create_sql
    if src_table != dst_table:
        result = result.replace(f"`{src_table}`", f"`{dst_table}`", 1)
        result = re.sub(
            rf"CREATE TABLE `{re.escape(src_table)}`",
            f"CREATE TABLE `{dst_table}`",
            result,
            count=1,
        )
    return result


def get_columns(conn: MySQLdb.Connection, table: str) -> list[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
            """,
            (table,),
        )
        rows = cursor.fetchall()
    if not rows:
        raise SystemExit(f"无法读取列信息: {table}")
    return [str(row[0]) for row in rows]


def get_row_count(conn: MySQLdb.Connection, table: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
        row = cursor.fetchone()
    return int(row[0] if row else 0)


def get_primary_key(conn: MySQLdb.Connection, table: str) -> str | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
              AND CONSTRAINT_NAME = 'PRIMARY'
            ORDER BY ORDINAL_POSITION
            LIMIT 1
            """,
            (table,),
        )
        row = cursor.fetchone()
    return str(row[0]) if row else None


def create_target_table(
    dst: MySQLdb.Connection,
    *,
    dst_table: str,
    create_sql: str,
    replace: bool,
    dry_run: bool,
) -> None:
    if replace:
        drop_sql = f"DROP TABLE IF EXISTS `{dst_table}`"
        if dry_run:
            print(f"[dry-run] {drop_sql}")
        else:
            with dst.cursor() as cursor:
                cursor.execute(drop_sql)
            dst.commit()

    if dry_run:
        print("[dry-run] CREATE TABLE ...")
        print(create_sql[:500] + ("..." if len(create_sql) > 500 else ""))
        return

    with dst.cursor() as cursor:
        cursor.execute(create_sql)
    dst.commit()


def copy_rows(
    src: MySQLdb.Connection,
    dst: MySQLdb.Connection,
    *,
    src_table: str,
    dst_table: str,
    columns: list[str],
    pk: str | None,
    batch_size: int,
    dry_run: bool,
) -> int:
    total = get_row_count(src, src_table)
    if total == 0:
        print("源表无数据，跳过复制。")
        return 0

    col_sql = ", ".join(f"`{name}`" for name in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO `{dst_table}` ({col_sql}) VALUES ({placeholders})"

    copied = 0
    last_pk: Any = None

    print(f"开始复制数据，共 {total} 行，batch={batch_size}")

    while copied < total:
        if pk:
            if last_pk is None:
                select_sql = (
                    f"SELECT {col_sql} FROM `{src_table}` ORDER BY `{pk}` ASC LIMIT %s"
                )
                params: tuple[Any, ...] = (batch_size,)
            else:
                select_sql = (
                    f"SELECT {col_sql} FROM `{src_table}` "
                    f"WHERE `{pk}` > %s ORDER BY `{pk}` ASC LIMIT %s"
                )
                params = (last_pk, batch_size)
        else:
            select_sql = f"SELECT {col_sql} FROM `{src_table}` LIMIT %s OFFSET %s"
            params = (batch_size, copied)

        with src.cursor(DictCursor) as cursor:
            cursor.execute(select_sql, params)
            rows = cursor.fetchall()

        if not rows:
            break

        if dry_run:
            copied += len(rows)
            if pk and rows:
                last_pk = rows[-1][pk]
            print(f"[dry-run] 已模拟复制 {copied}/{total}")
            continue

        values = [tuple(row[col] for col in columns) for row in rows]
        with dst.cursor() as cursor:
            cursor.executemany(insert_sql, values)
        dst.commit()

        copied += len(rows)
        if pk and rows:
            last_pk = rows[-1][pk]
        print(f"已复制 {copied}/{total}")

    return copied


def main() -> int:
    args = parse_args()
    src_table = args.table.strip()
    dst_table = (args.dst_table or args.table).strip()
    if not src_table or not dst_table:
        raise SystemExit("表名不能为空")

    print("连接源库（只读）...")
    src = connect(
        host=args.src_host,
        port=args.src_port,
        db=args.src_db,
        user=args.src_user,
        password=args.src_password,
    )
    print("连接目标库...")
    dst = connect(
        host=args.dst_host,
        port=args.dst_port,
        db=args.dst_db,
        user=args.dst_user,
        password=args.dst_password,
    )

    try:
        src_version = fetch_version(src)
        dst_version = fetch_version(dst)
        print(f"源库版本: {src_version}")
        print(f"目标库版本: {dst_version}")

        if not table_exists(src, src_table):
            raise SystemExit(f"源表不存在: {args.src_db}.{src_table}")

        create_sql = get_create_table_sql(src, src_table)
        create_sql = rewrite_create_table_for_target(
            create_sql,
            src_table=src_table,
            dst_table=dst_table,
        )

        if table_exists(dst, dst_table):
            if args.replace_dst:
                print(f"目标表 {dst_table} 已存在，将删除后重建（仅目标库）。")
            else:
                raise SystemExit(
                    f"目标表已存在: {args.dst_db}.{dst_table}。"
                    "如需覆盖请加 --replace-dst（只影响目标库，不动源库）。"
                )
        else:
            print(f"将在目标库创建表: {dst_table}")

        columns = get_columns(src, src_table)
        pk = get_primary_key(src, src_table)
        if pk:
            print(f"主键: {pk}")
        else:
            print("警告: 未检测到主键，将使用 LIMIT/OFFSET 复制（大表较慢）。")

        create_target_table(
            dst,
            dst_table=dst_table,
            create_sql=create_sql,
            replace=args.replace_dst,
            dry_run=args.dry_run,
        )
        copied = copy_rows(
            src,
            dst,
            src_table=src_table,
            dst_table=dst_table,
            columns=columns,
            pk=pk,
            batch_size=max(1, args.batch_size),
            dry_run=args.dry_run,
        )

        if args.dry_run:
            print(f"[dry-run] 完成。预计复制 {copied} 行，源库未被修改。")
        else:
            dst_count = get_row_count(dst, dst_table)
            print(f"完成。目标表 {args.dst_db}.{dst_table} 现有 {dst_count} 行，源库未被修改。")
        return 0
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    sys.exit(main())
