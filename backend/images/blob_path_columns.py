"""Detect varchar/text columns that store storage paths (upload/… / templates/…)."""
from __future__ import annotations

import logging
import re
from typing import Any

from utils.path_builder import is_valid_storage_path, normalize_relative_path

logger = logging.getLogger(__name__)

PATH_VALUE_TYPES = frozenset(
    {
        "varchar",
        "char",
        "text",
        "tinytext",
        "mediumtext",
        "longtext",
        "nvarchar",
        "nchar",
    }
)

# Soft name hint for catalog list (no row sampling).
_PATH_NAME_HINT_RE = re.compile(
    r"(path|image|photo|pic|fingerprint|thumb|img|blob)",
    re.IGNORECASE,
)


def looks_like_storage_path(value: Any) -> bool:
    """True if value is (or decodes to) an upload/templates storage path."""
    if value is None:
        return False
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        try:
            text = bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return False
    else:
        text = str(value)
    text = normalize_relative_path(text.strip())
    if not text:
        return False
    if is_valid_storage_path(text):
        return True
    # Accept exported paths that may not match UUID regex strictly but use our layout.
    lower = text.lower()
    return lower.startswith("upload/") or lower.startswith("templates/")


def column_name_suggests_path(name: str) -> bool:
    return bool(_PATH_NAME_HINT_RE.search(name or ""))


def is_path_value_type(data_type: str | None) -> bool:
    return (data_type or "").lower() in PATH_VALUE_TYPES


def detect_path_columns_by_sample(
    conn,
    *,
    table: str,
    columns: list[dict[str, Any]],
    sample_limit: int = 40,
) -> list[dict[str, Any]]:
    """Sample string columns; mark those whose values are mostly storage paths."""
    if conn.vendor != "mysql":
        return []
    candidates = [
        c
        for c in columns
        if is_path_value_type(c.get("data_type")) and not c.get("is_blob")
    ]
    if not candidates:
        return []

    found: list[dict[str, Any]] = []
    with conn.cursor() as cursor:
        for col in candidates:
            name = str(col.get("name") or "").strip()
            if not name:
                continue
            try:
                cursor.execute(
                    f"SELECT `{name}` FROM `{table}` "
                    f"WHERE `{name}` IS NOT NULL AND TRIM(CAST(`{name}` AS CHAR)) <> '' "
                    f"LIMIT %s",
                    [sample_limit],
                )
                rows = cursor.fetchall()
            except Exception:
                logger.debug("path-column sample failed table=%s col=%s", table, name, exc_info=True)
                continue
            if not rows:
                # Empty table: still offer name-hint columns as path candidates.
                if column_name_suggests_path(name):
                    found.append(
                        {
                            "column": name,
                            "data_type": (col.get("data_type") or "").lower(),
                            "role": "path",
                            "detected_by": "name_hint",
                        }
                    )
                continue
            hits = sum(1 for (val,) in rows if looks_like_storage_path(val))
            # Majority of nonempty samples look like paths.
            if hits >= max(1, (len(rows) + 1) // 2):
                found.append(
                    {
                        "column": name,
                        "data_type": (col.get("data_type") or "").lower(),
                        "role": "path",
                        "detected_by": "sample",
                    }
                )
    return found


def merge_image_columns(
    blob_columns: list[dict[str, Any]] | None,
    path_columns: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Unified image-column list for UI (blob first, then path)."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for src, role in ((blob_columns or [], "blob"), (path_columns or [], "path")):
        for item in src:
            name = str(item.get("column") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            items.append(
                {
                    "column": name,
                    "data_type": (item.get("data_type") or "").lower(),
                    "role": item.get("role") or role,
                }
            )
    return items
