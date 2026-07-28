"""Route SQL against known simulated tables through fetch_simulated_table_rows."""
from __future__ import annotations

import re
from dataclasses import dataclass

from django.utils import timezone

from images.blob_table_view_service import (
    BlobTableViewError,
    build_ephemeral_table_view,
    fetch_simulated_table_rows,
)
from images.models import BlobTableView
from images.blob_migration_service import validate_where_clause
from sqlquery.exceptions import SqlExecutionError

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


@dataclass(frozen=True)
class ParsedSimulatedSelect:
    table: str
    extra_where: str
    limit: int
    offset: int


def _normalize_table_name(name: str) -> str:
    return (name or "").strip().strip("`").split(".")[-1]


def parse_simulated_select(sql: str, *, expected_table: str) -> ParsedSimulatedSelect | None:
    """Parse LIMIT/OFFSET/WHERE for a single-table SELECT on expected_table."""
    cleaned = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    cleaned = re.sub(r"(?:--|#)[^\n\r]*", " ", cleaned)
    cleaned = cleaned.strip()
    if not re.match(r"^\s*select\b", cleaned, re.IGNORECASE):
        return None

    from_match = re.search(
        r"\bfrom\s+((?:[`\"]?[\w]+[`\"]?)\.)?[`\"]?([\w]+)[`\"]?",
        cleaned,
        re.IGNORECASE,
    )
    if not from_match:
        return None
    table = _normalize_table_name(from_match.group(2))
    if table.lower() != _normalize_table_name(expected_table).lower():
        return None

    limit = _DEFAULT_LIMIT
    offset = 0
    limit_match = re.search(
        r"\blimit\s+(\d+)(?:\s*,\s*(\d+)|\s+offset\s+(\d+))?",
        cleaned,
        re.IGNORECASE,
    )
    if limit_match:
        first = int(limit_match.group(1))
        second = limit_match.group(2) or limit_match.group(3)
        if limit_match.group(2):
            offset = first
            limit = int(second)
        else:
            limit = first
            if limit_match.group(3):
                offset = int(limit_match.group(3))

    limit = max(1, min(limit, _MAX_LIMIT))
    offset = max(0, offset)

    extra_where = ""
    where_match = re.search(
        r"\bwhere\s+(.+?)(?=\border\s+by\b|\blimit\b|\bgroup\s+by\b|\bhaving\b|$)",
        cleaned,
        re.IGNORECASE | re.DOTALL,
    )
    if where_match:
        extra_where = where_match.group(1).strip().rstrip(";")
        try:
            validate_where_clause(extra_where)
        except Exception as exc:
            raise SqlExecutionError(f"WHERE 条件无效: {exc}") from exc

    return ParsedSimulatedSelect(
        table=table,
        extra_where=extra_where,
        limit=limit,
        offset=offset,
    )


def _load_view_by_id(view_id: int) -> BlobTableView:
    try:
        return BlobTableView.objects.get(pk=view_id)
    except BlobTableView.DoesNotExist as exc:
        raise SqlExecutionError(f"浏览配置不存在: id={view_id}") from exc


def resolve_simulation_view(
    *,
    view_id: int | None,
    db_alias: str | None,
    connection_id: int | None,
    database: str | None,
    source_table: str | None,
    source_pk_column: str | None,
    blob_columns: list[str] | None,
    source_object_type: str | None,
    path_lookup_table: str | None,
) -> BlobTableView | None:
    if view_id:
        return _load_view_by_id(view_id)

    table = (source_table or "").strip()
    cols = [c.strip() for c in (blob_columns or []) if (c or "").strip()]
    if not table or not cols:
        return None

    alias = (db_alias or "default").strip() or "default"
    if connection_id:
        from images.external_db_service import external_alias

        alias = external_alias(connection_id)

    try:
        return build_ephemeral_table_view(
            db_alias=alias,
            database_name=(database or "").strip(),
            source_table=table,
            blob_columns=cols,
            source_pk_column=(source_pk_column or "id").strip() or "id",
            source_object_type=source_object_type,
            path_lookup_table=(path_lookup_table or "").strip(),
        )
    except BlobTableViewError as exc:
        raise SqlExecutionError(str(exc)) from exc


def simulated_fetch_to_sql_payload(fetch_result: dict, *, sql: str, started) -> dict[str, object]:
    column_meta = fetch_result.get("columns") or []
    col_names = [col["name"] for col in column_meta]
    rows_out: list[list] = []
    for row in fetch_result.get("rows") or []:
        if not isinstance(row, dict):
            continue
        rows_out.append([row.get(name) for name in col_names])

    elapsed_ms = int((timezone.now() - started).total_seconds() * 1000)
    total = int(fetch_result.get("total") or -1)
    truncated = bool(fetch_result.get("has_more"))
    if total >= 0 and len(rows_out) >= total:
        truncated = False

    return {
        "sql": sql,
        "original_sql": sql,
        "remote_sql": fetch_result.get("remote_sql") or "",
        "columns": col_names,
        "column_meta": column_meta,
        "rows": rows_out,
        "row_count": len(rows_out),
        "truncated": truncated,
        "elapsed_ms": elapsed_ms,
        "simulated": True,
        "blob_mode": "path",
        "db_alias": "",
        "database": "",
        "connection_id": None,
        "view_id": fetch_result.get("view_id"),
        "total": total,
        "offset": fetch_result.get("offset"),
        "limit": fetch_result.get("limit"),
    }


def try_execute_simulated_sql(
    sql: str,
    *,
    view_id: int | None = None,
    db_alias: str | None = None,
    connection_id: int | None = None,
    database: str | None = None,
    source_table: str | None = None,
    source_pk_column: str | None = None,
    blob_columns: list[str] | None = None,
    source_object_type: str | None = None,
    path_lookup_table: str | None = None,
) -> dict[str, object] | None:
    view = resolve_simulation_view(
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
    if view is None:
        return None

    parsed = parse_simulated_select(sql, expected_table=view.source_table)
    if parsed is None:
        raise SqlExecutionError(
            f"模拟 SQL 仅支持查询当前表 `{view.source_table}`（SELECT ... FROM {view.source_table} [WHERE ...] [LIMIT n]）"
        )

    started = timezone.now()
    try:
        fetch_result = fetch_simulated_table_rows(
            view,
            offset=parsed.offset,
            limit=parsed.limit,
            extra_where=parsed.extra_where,
            touch_last_viewed=bool(view.pk),
        )
    except BlobTableViewError as exc:
        raise SqlExecutionError(str(exc)) from exc

    payload = simulated_fetch_to_sql_payload(fetch_result, sql=sql, started=started)
    payload["db_alias"] = view.db_alias
    payload["database"] = view.database_name or database or ""
    payload["connection_id"] = connection_id
    return payload
