"""SQL execution service — Step 13 + PR3 external DB context."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import close_old_connections, connections
from django.utils import timezone

from sqlquery.cell_format import format_blob_placeholder, serialize_sql_cell
from sqlquery.simulated_sql import try_execute_simulated_sql
from sqlquery.sql_rewrite import rewrite_sql_for_blob_performance
from utils.sql_validator import SqlValidationError, validate_sql

logger = logging.getLogger(__name__)


from sqlquery.exceptions import SqlExecutionError

@dataclass
class SqlConnectionContext:
    db_alias: str
    database: str
    connection_id: int | None = None


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


def _serialize_sql_row(
    record: tuple[Any, ...],
    *,
    columns: list[str],
    blob_length_columns: frozenset[str],
) -> list[Any]:
    row: list[Any] = []
    for idx, value in enumerate(record):
        col = columns[idx] if idx < len(columns) else ""
        if col in blob_length_columns and isinstance(value, int):
            row.append(format_blob_placeholder(value))
        else:
            row.append(serialize_sql_cell(value))
    return row


def _execute_in_thread(
    sql: str,
    max_rows: int,
    *,
    context: SqlConnectionContext,
    exclude_blob_star: bool = True,
) -> tuple[list[str], list[list[Any]], bool, str, frozenset[str]]:
    from images.external_db_service import db_alias_session

    db_switch = context.database or None
    executed_sql = sql
    blob_length_columns: frozenset[str] = frozenset()
    with db_alias_session(context.db_alias, database=db_switch) as session_alias:
        connection = connections[session_alias]

        if exclude_blob_star and connection.vendor == "mysql":
            rewrite = rewrite_sql_for_blob_performance(
                sql,
                conn=connection,
                database=context.database,
            )
            executed_sql = rewrite.sql
            blob_length_columns = rewrite.blob_length_columns

        with connection.cursor() as cursor:
            cursor.execute(executed_sql)
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
                    rows.append(
                        _serialize_sql_row(
                            record,
                            columns=columns,
                            blob_length_columns=blob_length_columns,
                        )
                    )
                    if len(rows) >= max_rows:
                        truncated = True
                        break
                if truncated:
                    break

            if not truncated:
                extra = cursor.fetchone()
                if extra is not None:
                    truncated = True

    return columns, rows, truncated, executed_sql, blob_length_columns


def execute_select_sql(
    sql: str,
    *,
    db_alias: str | None = None,
    connection_id: int | None = None,
    database: str | None = None,
    view_id: int | None = None,
    source_table: str | None = None,
    source_pk_column: str | None = None,
    blob_columns: list[str] | None = None,
    source_object_type: str | None = None,
    path_lookup_table: str | None = None,
    blob_mode: str = "path",
) -> dict[str, Any]:
    """
    Validate and execute a SELECT query.

    When blob_mode=path and a simulated table context is provided, uses the same
    optimized path as「表数据」browse (no BLOB bytes over the wire).
    """
    require_where = getattr(settings, "SQL_REQUIRE_WHERE_FOR_SELECT_STAR", False)
    cleaned = validate_sql(
        sql,
        require_where_for_select_star=require_where,
    )

    mode = (blob_mode or "path").strip().lower()
    if mode not in {"path", "placeholder", "raw"}:
        raise SqlExecutionError("blob_mode 无效，应为 path / placeholder / raw")

    started = timezone.now()

    if mode == "path":
        try:
            simulated = try_execute_simulated_sql(
                cleaned,
                view_id=view_id,
                db_alias=db_alias,
                connection_id=connection_id,
                database=database,
                source_table=source_table,
                source_pk_column=source_pk_column,
                blob_columns=blob_columns,
                source_object_type=source_object_type,
                path_lookup_table=path_lookup_table,
            )
        except SqlExecutionError:
            raise
        except Exception as exc:
            logger.exception("simulated SQL failed")
            raise SqlExecutionError(str(exc)) from exc
        if simulated is not None:
            return simulated

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

    exclude_blob_star = mode != "raw"

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            _execute_in_thread,
            cleaned,
            max_rows,
            context=context,
            exclude_blob_star=exclude_blob_star,
        )
        try:
            columns, rows, truncated, executed_sql, _blob_length_cols = future.result(timeout=timeout)
        except FuturesTimeout as exc:
            future.cancel()
            # Never connections.close_all() — tears down default for sibling requests.
            close_old_connections()
            raise SqlExecutionError(f"查询超时（>{timeout}s）") from exc
        except SqlValidationError:
            raise
        except Exception as exc:
            logger.exception("SQL execution failed")
            raise SqlExecutionError(f"SQL 执行失败: {exc}") from exc

    elapsed_ms = int((timezone.now() - started).total_seconds() * 1000)

    return {
        "sql": executed_sql,
        "original_sql": cleaned,
        "columns": columns,
        "column_meta": [{"name": name, "is_path_substitute": False} for name in columns],
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "elapsed_ms": elapsed_ms,
        "simulated": False,
        "blob_mode": mode if mode != "path" else "placeholder",
        "db_alias": context.db_alias,
        "database": context.database,
        "connection_id": context.connection_id,
    }
