"""SQL template storage — Step 13 (file-based, no extra DB table)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings

BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "builtin-recent",
        "name": "最近上传的图片",
        "sql": "SELECT id, image_name, image_path, upload_time, upload_user\n"
        "FROM image_info\nWHERE is_delete = 0\nORDER BY upload_time DESC\nLIMIT 20",
        "builtin": True,
    },
    {
        "id": "builtin-by-category",
        "name": "按分类统计",
        "sql": "SELECT c.category_name, COUNT(i.id) AS image_count\n"
        "FROM image_category c\n"
        "LEFT JOIN image_info i ON i.category_id = c.id AND i.is_delete = 0\n"
        "GROUP BY c.id, c.category_name\nORDER BY image_count DESC",
        "builtin": True,
    },
    {
        "id": "builtin-large-files",
        "name": "大文件图片 (>1MB)",
        "sql": "SELECT id, image_name, image_path, file_size, upload_time\n"
        "FROM image_info\nWHERE is_delete = 0 AND file_size > 1048576\n"
        "ORDER BY file_size DESC\nLIMIT 50",
        "builtin": True,
    },
]


def _store_path() -> Path:
    data_dir = Path(settings.BASE_DIR) / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir / "sql_templates.json"


def _load_custom() -> list[dict[str, Any]]:
    path = _store_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [t for t in data if isinstance(t, dict) and not t.get("builtin")]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_custom(templates: list[dict[str, Any]]) -> None:
    path = _store_path()
    path.write_text(json.dumps(templates, ensure_ascii=False, indent=2), encoding="utf-8")


def list_templates() -> list[dict[str, Any]]:
    return BUILTIN_TEMPLATES + _load_custom()


def add_template(name: str, sql: str) -> dict[str, Any]:
    name = name.strip()
    sql = sql.strip()
    if not name or not sql:
        raise ValueError("模板名称和 SQL 不能为空")

    custom = _load_custom()
    new_id = f"custom-{len(custom) + 1}"
    entry = {"id": new_id, "name": name, "sql": sql, "builtin": False}
    custom.append(entry)
    _save_custom(custom)
    return entry
