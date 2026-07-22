"""Optional path write-back after fingerprint ZIP import.

Writes relative storage paths (upload/... / templates/...) into a user-selected
business table via UPDATE, matched by person_id + finger_position.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from django.db import connections

from images.blob_migration_service import BlobMigrationError, validate_identifier
from images.external_db_service import ExternalDbError, db_alias_session, external_alias

logger = logging.getLogger(__name__)

MAX_WRITEBACK_ERRORS = 20


class PathWritebackError(Exception):
    """Invalid path write-back configuration."""


@dataclass
class WritebackCounters:
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "WritebackCounters") -> None:
        self.updated += other.updated
        self.skipped += other.skipped
        self.failed += other.failed
        for err in other.errors:
            if len(self.errors) >= MAX_WRITEBACK_ERRORS:
                break
            self.errors.append(err)

    def to_dict(self) -> dict[str, Any]:
        return {
            "writeback_updated": self.updated,
            "writeback_skipped": self.skipped,
            "writeback_failed": self.failed,
            "writeback_errors": list(self.errors)[:MAX_WRITEBACK_ERRORS],
        }


def _quote_ident(name: str) -> str:
    return f"`{validate_identifier(name)}`"


def _truthy_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_path_writeback_config(raw: Any) -> dict | None:
    """
    Normalize API/job options into an internal config dict, or None if disabled.

    Raises PathWritebackError when enabled but invalid.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PathWritebackError(f"path_writeback JSON 无效: {exc}") from exc
    if not isinstance(raw, dict):
        raise PathWritebackError("path_writeback 须为对象")
    if not _truthy_enabled(raw.get("enabled")):
        return None

    try:
        table = validate_identifier(str(raw.get("table") or ""), label="写回表名")
        match = raw.get("match") if isinstance(raw.get("match"), dict) else {}
        paths = raw.get("paths") if isinstance(raw.get("paths"), dict) else {}

        person_col = validate_identifier(
            str(match.get("person_id_column") or ""), label="人员号列"
        )
        finger_col = validate_identifier(
            str(match.get("finger_column") or ""), label="指位列"
        )

        image_column_raw = str(paths.get("image_column") or "").strip()
        image_column = (
            validate_identifier(image_column_raw, label="图像路径列") if image_column_raw else ""
        )

        templates_raw = paths.get("templates") if isinstance(paths.get("templates"), dict) else {}
        templates: dict[str, str] = {}
        for key, col in templates_raw.items():
            layer_key = str(key or "").strip().lower()
            col_name = str(col or "").strip()
            if not layer_key or not col_name:
                continue
            if not layer_key.replace("_", "").isalnum():
                raise PathWritebackError(f"模板映射 key 无效: {key!r}")
            templates[layer_key] = validate_identifier(col_name, label=f"模板路径列({layer_key})")

        if not image_column and not templates:
            raise PathWritebackError("启用路径写回时须至少指定 image_column 或 templates 映射")

        connection_id = raw.get("connection_id")
        db_alias = str(raw.get("db_alias") or "").strip()
        if connection_id not in (None, ""):
            try:
                connection_id = int(connection_id)
            except (TypeError, ValueError) as exc:
                raise PathWritebackError("connection_id 无效") from exc
            db_alias = external_alias(connection_id)
        else:
            connection_id = None
            db_alias = db_alias or "default"

        database = str(raw.get("database") or "").strip() or None
        if database:
            validate_identifier(database, label="数据库名")
    except BlobMigrationError as exc:
        raise PathWritebackError(str(exc)) from exc

    return {
        "enabled": True,
        "connection_id": connection_id,
        "db_alias": db_alias,
        "database": database,
        "table": table,
        "match": {
            "person_id_column": person_col,
            "finger_column": finger_col,
        },
        "paths": {
            "image_column": image_column,
            "templates": templates,
        },
    }


def _resolve_alias(config: dict) -> str:
    if config.get("connection_id") is not None:
        return external_alias(int(config["connection_id"]))
    return str(config.get("db_alias") or "default")


def writeback_side_paths(
    config: dict,
    *,
    person_id: str,
    finger_position: str,
    image_path: str | None = None,
    template_paths: dict[str, str] | None = None,
) -> WritebackCounters:
    """
    UPDATE one business row for (person_id, finger_position).

    template_paths keys are layer_key (e.g. bidiso, neuiso).
    """
    counters = WritebackCounters()
    person_id = str(person_id or "").strip()
    finger_position = str(finger_position or "").strip()
    if not person_id or not finger_position:
        counters.skipped += 1
        return counters

    set_parts: list[str] = []
    params: list[Any] = []
    image_col = (config.get("paths") or {}).get("image_column") or ""
    if image_col and image_path:
        set_parts.append(f"{_quote_ident(image_col)}=%s")
        params.append(image_path)

    templates_map: dict[str, str] = (config.get("paths") or {}).get("templates") or {}
    for layer_key, path in (template_paths or {}).items():
        col = templates_map.get(str(layer_key).lower())
        if not col or not path:
            continue
        set_parts.append(f"{_quote_ident(col)}=%s")
        params.append(path)

    if not set_parts:
        counters.skipped += 1
        return counters

    table = _quote_ident(config["table"])
    person_col = _quote_ident(config["match"]["person_id_column"])
    finger_col = _quote_ident(config["match"]["finger_column"])
    sql = (
        f"UPDATE {table} SET {', '.join(set_parts)} "
        f"WHERE {person_col}=%s AND {finger_col}=%s"
    )
    params.extend([person_id, finger_position])

    alias = _resolve_alias(config)
    database = config.get("database")
    try:
        with db_alias_session(alias, database=database) as session_alias:
            conn = connections[session_alias]
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                affected = int(cursor.rowcount or 0)
            # Some MySQL drivers report -1; treat as unknown success if no error.
            if affected == 0:
                counters.skipped += 1
            else:
                counters.updated += 1 if affected < 0 else affected
    except (PathWritebackError, ExternalDbError) as exc:
        counters.failed += 1
        counters.errors.append(f"{person_id}/{finger_position}: {exc}"[:240])
        logger.warning("path writeback failed: %s", exc)
    except Exception as exc:
        counters.failed += 1
        counters.errors.append(f"{person_id}/{finger_position}: {exc}"[:240])
        logger.warning(
            "path writeback failed person=%s finger=%s: %s",
            person_id,
            finger_position,
            exc,
            exc_info=True,
        )
    return counters


def writeback_pair_paths(
    config: dict | None,
    *,
    finger_position: str,
    sides: list[dict[str, Any]],
) -> WritebackCounters:
    """
    Write paths for left/right sides of one pair.

    Each side dict: {person_id, image_path, template_paths: {layer_key: path}}
    """
    total = WritebackCounters()
    if not config:
        return total
    for side in sides:
        part = writeback_side_paths(
            config,
            person_id=str(side.get("person_id") or ""),
            finger_position=finger_position,
            image_path=side.get("image_path"),
            template_paths=side.get("template_paths") or {},
        )
        total.merge(part)
    return total
