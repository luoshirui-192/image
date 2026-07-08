"""Shared helpers for BLOB migration / browse schema fields (PR1+)."""
from __future__ import annotations

import json

OBJECT_TYPE_TABLE = "table"
OBJECT_TYPE_VIEW = "view"


def parse_blob_columns(blob_columns_raw: str | None, blob_column: str | None = None) -> list[str]:
    raw = (blob_columns_raw or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            cols = [str(item).strip() for item in parsed if str(item).strip()]
            if cols:
                return cols
    single = (blob_column or "").strip()
    return [single] if single else []


def serialize_blob_columns(columns: list[str] | None) -> str:
    if not columns:
        return ""
    cleaned = [str(col).strip() for col in columns if str(col).strip()]
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else ""


def primary_blob_column(blob_columns_raw: str | None, blob_column: str | None = None) -> str:
    cols = parse_blob_columns(blob_columns_raw, blob_column)
    return cols[0] if cols else (blob_column or "").strip()


def normalize_object_type(value: str | None, *, default: str = OBJECT_TYPE_TABLE) -> str:
    normalized = (value or default).strip().lower()
    if normalized in {OBJECT_TYPE_TABLE, "base table", "base_table"}:
        return OBJECT_TYPE_TABLE
    if normalized in {OBJECT_TYPE_VIEW, "sql_view", "sql view"}:
        return OBJECT_TYPE_VIEW
    return default


def parse_blob_column_path_mappings(raw: str | None) -> list[dict[str, str]]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    results: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        view_column = str(item.get("view_column") or "").strip()
        lookup_table = str(item.get("lookup_table") or "").strip()
        source_id_column = str(item.get("source_id_column") or "").strip()
        source_column = str(item.get("source_column") or view_column).strip()
        if view_column and lookup_table and source_id_column:
            results.append(
                {
                    "view_column": view_column,
                    "lookup_table": lookup_table,
                    "source_id_column": source_id_column,
                    "source_column": source_column,
                }
            )
    return results


def serialize_blob_column_path_mappings(mappings: list[dict[str, str]] | None) -> str:
    if not mappings:
        return ""
    cleaned: list[dict[str, str]] = []
    for item in mappings:
        view_column = str(item.get("view_column") or "").strip()
        lookup_table = str(item.get("lookup_table") or "").strip()
        source_id_column = str(item.get("source_id_column") or "").strip()
        source_column = str(item.get("source_column") or view_column).strip()
        if not view_column or not lookup_table or not source_id_column:
            continue
        cleaned.append(
            {
                "view_column": view_column,
                "lookup_table": lookup_table,
                "source_id_column": source_id_column,
                "source_column": source_column,
            }
        )
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else ""


def map_storage_table(
    *,
    source_table: str,
    source_object_type: str | None = None,
    path_lookup_table: str | None = None,
) -> str:
    """Table name used in image_source_map (base table for SQL views)."""
    manual = (path_lookup_table or "").strip()
    if manual:
        return manual
    if normalize_object_type(source_object_type) == OBJECT_TYPE_VIEW:
        raise ValueError("数据库视图需配置 path_lookup_table")
    return (source_table or "").strip()
