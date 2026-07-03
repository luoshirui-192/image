"""Runtime system settings — Step 22."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from django.conf import settings

ENV_PATH = Path(settings.BASE_DIR) / ".env"

EDITABLE_KEYS: dict[str, dict[str, Any]] = {
    "UPLOAD_ROOT": {"type": "str", "label": "上传根目录"},
    "MAX_UPLOAD_SIZE_MB": {"type": "int", "min": 1, "max": 500, "label": "单文件大小上限(MB)"},
    "THUMB_SIZE": {"type": "int", "min": 50, "max": 800, "label": "缩略图边长(px)"},
    "SQL_QUERY_TIMEOUT": {"type": "int", "min": 1, "max": 120, "label": "SQL 查询超时(秒)"},
    "SQL_MAX_ROWS": {"type": "int", "min": 10, "max": 10000, "label": "SQL 最大返回行数"},
    "SQL_REQUIRE_WHERE_FOR_SELECT_STAR": {
        "type": "bool",
        "label": "SELECT * 必须带 WHERE",
    },
    "DELETED_IMAGE_RETENTION_DAYS": {"type": "int", "min": 1, "max": 365, "label": "逻辑删除保留天数"},
    "LOG_RETENTION_DAYS": {"type": "int", "min": 7, "max": 3650, "label": "操作日志保留天数"},
    "IMAGE_ACCESS_TOKEN_TTL": {"type": "int", "min": 60, "max": 86400, "label": "图片访问令牌有效期(秒)"},
}

READONLY_KEYS = (
    "DB_ENGINE",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "THUMB_CACHE_ROOT",
)


def _bool_to_env(value: bool) -> str:
    return "true" if value else "false"


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


def _coerce_value(key: str, raw: Any) -> Any:
    meta = EDITABLE_KEYS[key]
    kind = meta["type"]
    if kind == "int":
        value = int(raw)
        if "min" in meta and value < meta["min"]:
            raise ValueError(f"{meta['label']}不能小于 {meta['min']}")
        if "max" in meta and value > meta["max"]:
            raise ValueError(f"{meta['label']}不能大于 {meta['max']}")
        return value
    if kind == "bool":
        return _parse_bool(raw)
    value = str(raw).strip()
    if not value:
        raise ValueError(f"{meta['label']}不能为空")
    return value


def _apply_to_django(key: str, value: Any) -> None:
    setattr(settings, key, value)
    if key == "MAX_UPLOAD_SIZE_MB":
        settings.MAX_UPLOAD_SIZE_BYTES = int(value) * 1024 * 1024
    os.environ[key] = _bool_to_env(value) if isinstance(value, bool) else str(value)


def _write_env_file(updates: dict[str, str]) -> None:
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    for key, value in updates.items():
        pattern = re.compile(rf"^{re.escape(key)}=")
        replaced = False
        new_lines: list[str] = []
        for line in lines:
            if pattern.match(line):
                new_lines.append(f"{key}={value}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append(f"{key}={value}")
        lines = new_lines

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def get_system_config() -> dict:
    editable = {}
    for key, meta in EDITABLE_KEYS.items():
        current = getattr(settings, key)
        editable[key] = {
            "value": current,
            "label": meta["label"],
            "type": meta["type"],
            "min": meta.get("min"),
            "max": meta.get("max"),
        }

    readonly = {key: getattr(settings, key, "") for key in READONLY_KEYS}
    return {
        "editable": editable,
        "readonly": readonly,
        "env_file": str(ENV_PATH),
    }


def update_system_config(payload: dict[str, Any]) -> dict:
    if not payload:
        raise ValueError("未提供任何配置项")

    unknown = [k for k in payload if k not in EDITABLE_KEYS]
    if unknown:
        raise ValueError(f"不支持的配置项: {', '.join(unknown)}")

    coerced: dict[str, Any] = {}
    for key, raw in payload.items():
        coerced[key] = _coerce_value(key, raw)

    if "UPLOAD_ROOT" in coerced:
        path = Path(coerced["UPLOAD_ROOT"])
        path.mkdir(parents=True, exist_ok=True)

    env_updates: dict[str, str] = {}
    for key, value in coerced.items():
        env_updates[key] = _bool_to_env(value) if isinstance(value, bool) else str(value)
        _apply_to_django(key, value)

    _write_env_file(env_updates)
    return get_system_config()
