"""Serialize SQL result cells — avoid decoding binary BLOB as UTF-8."""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


def format_blob_placeholder(size: int) -> str:
    if size <= 0:
        return "[empty BLOB]"
    if size >= 1024 * 1024:
        return f"[BLOB {size / (1024 * 1024):.1f} MB]"
    if size >= 1024:
        return f"[BLOB {size / 1024:.1f} KB]"
    return f"[BLOB {size} bytes]"


def serialize_sql_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat(sep=" ", timespec="seconds") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return format_blob_placeholder(len(value))
    if isinstance(value, dict):
        return value
    return value
