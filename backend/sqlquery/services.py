"""SQL execution service — Step 13."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from decimal import Decimal
from datetime import date, datetime, time
from typing import Any

from django.conf import settings
from django.db import connections
from django.utils import timezone

from utils.sql_validator import SqlValidationError, validate_sql

logger = logging.getLogger(__name__)


class SqlExecutionError(Exception):
    """Raised when SQL execution fails or times out."""


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


def _execute_in_thread(sql: str, max_rows: int) -> tuple[list[str], list[list[Any]], bool]:
    connection = connections["default"]
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


def execute_select_sql(sql: str) -> dict[str, Any]:
    """
    Validate and execute a SELECT query.

    Returns dict with columns, rows, row_count, truncated, elapsed_ms.
    """
    require_where = getattr(settings, "SQL_REQUIRE_WHERE_FOR_SELECT_STAR", False)
    cleaned = validate_sql(
        sql,
        require_where_for_select_star=require_where,
    )

    max_rows = settings.SQL_MAX_ROWS
    timeout = settings.SQL_QUERY_TIMEOUT
    started = timezone.now()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_execute_in_thread, cleaned, max_rows)
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
    }
