"""SQL execution service — Step 13 + PR3 external DB context."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import connections
from django.utils import timezone

from utils.sql_validator import SqlValidationError, validate_sql

logger = logging.getLogger(__name__)


class SqlExecutionError(Exception):
    """Raised when SQL execution fails or times out."""


@dataclass
class SqlConnectionContext:
    db_alias: str
    database: str
    connection_id: int | None = None


def _serialize_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat(sep=" ", timespec="seconds") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return value


def resolve_sql_connection_context(
    *,
    db_alias: str | None = None,
    connection_id: int | None = None,
    database: str | None = None,
) -> SqlConnectionContext:
    from images.external_db_service import external_alias, validate_db_alias_reference
    from images.models import ExternalDbConnection

    if connection_id is not None:
        try:
            record = ExternalDbConnection.objects.get(pk=connection_id, enabled=1)
        except ExternalDbConnection.DoesNotExist as exc:
            raise SqlExecutionError(f"外部库连接不存在或已禁用: id={connection_id}") from exc
        alias = external_alias(record.id)
        db_name = (database or record.db_name or "").strip() or record.db_name
        return SqlConnectionContext(db_alias=alias, database=db_name, connection_id=record.id)

    try:
        alias = validate_db_alias_reference((db_alias or "default").strip() or "default")
    except Exception as exc:
        raise SqlExecutionError(str(exc)) from exc
    db_name = (database or "").strip()
    if not db_name:
        cfg = connections.databases.get(alias, {})
        db_name = str(cfg.get("NAME") or "")
    return SqlConnectionContext(db_alias=alias, database=db_name)


def _execute_in_thread(
    sql: str,
    max_rows: int,
    *,
    context: SqlConnectionContext,
) -> tuple[list[str], list[list[Any]], bool]:
    from images.external_db_service import db_alias_session

    db_switch = context.database or None
    with db_alias_session(context.db_alias, database=db_switch):
        connection = connections[context.db_alias]
        connection.close()

        with connection.cursor() as cursor:
            cursor.execute(sql)
            if cursor.description is None:
                raise SqlExecutionError("查询未返回结果集")

            columns = [col[0] for col in cursor.description]
            rows: list[list[Any]] = []
            truncated = False

            while len(rows) < max_rows:
                batch = cursor.fetchmany(min(200, max_rows - len(rows)))
                if not batch:
                    break
                for record in batch:
                    rows.append([_serialize_cell(v) for v in record])
                    if len(rows) >= max_rows:
                        truncated = True
                        break
                if truncated:
                    break

            if not truncated:
                extra = cursor.fetchone()
                if extra is not None:
                    truncated = True

    return columns, rows, truncated


def execute_select_sql(
    sql: str,
    *,
    db_alias: str | None = None,
    connection_id: int | None = None,
    database: str | None = None,
) -> dict[str, Any]:
    """
    Validate and execute a SELECT query against default or external database.
    """
    require_where = getattr(settings, "SQL_REQUIRE_WHERE_FOR_SELECT_STAR", False)
    cleaned = validate_sql(
        sql,
        require_where_for_select_star=require_where,
    )

    try:
        context = resolve_sql_connection_context(
            db_alias=db_alias,
            connection_id=connection_id,
            database=database,
        )
    except Exception as exc:
        if isinstance(exc, SqlExecutionError):
            raise
        raise SqlExecutionError(str(exc)) from exc

    max_rows = settings.SQL_MAX_ROWS
    timeout = settings.SQL_QUERY_TIMEOUT
    started = timezone.now()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_execute_in_thread, cleaned, max_rows, context=context)
        try:
            columns, rows, truncated = future.result(timeout=timeout)
        except FuturesTimeout as exc:
            future.cancel()
            connections.close_all()
            raise SqlExecutionError(f"查询超时（>{timeout}s）") from exc
        except SqlValidationError:
            raise
        except Exception as exc:
            logger.exception("SQL execution failed")
            raise SqlExecutionError(f"SQL 执行失败: {exc}") from exc

    elapsed_ms = int((timezone.now() - started).total_seconds() * 1000)

    return {
        "sql": cleaned,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "elapsed_ms": elapsed_ms,
        "db_alias": context.db_alias,
        "database": context.database,
        "connection_id": context.connection_id,
    }
