"""Optional path write-back after fingerprint ZIP import.

For each imported image, INSERT one new row into a user-selected business table
and fill only the image path column. Other columns are left for the user to
fill later (UI / SQL).
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
    """`updated` counts successfully inserted rows (API field name kept for compat)."""

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
            "writeback_inserted": self.updated,
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

    Expected shape:
      {
        "enabled": true,
        "connection_id": 3,          # optional; else db_alias
        "db_alias": "default",
        "database": "biz_db",        # optional
        "table": "person_finger",
        "paths": { "image_column": "image_path" }
        # also accepts top-level "image_column"
      }
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
        paths = raw.get("paths") if isinstance(raw.get("paths"), dict) else {}
        image_column_raw = str(
            paths.get("image_column") or raw.get("image_column") or ""
        ).strip()
        if not image_column_raw:
            raise PathWritebackError("启用路径写回时须指定 image_column（图像路径列）")
        image_column = validate_identifier(image_column_raw, label="图像路径列")

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
        "paths": {"image_column": image_column},
        "image_column": image_column,
    }


def _resolve_alias(config: dict) -> str:
    if config.get("connection_id") is not None:
        return external_alias(int(config["connection_id"]))
    return str(config.get("db_alias") or "default")


def insert_image_path_row(config: dict, *, image_path: str) -> WritebackCounters:
    """INSERT one row with only the image path column filled."""
    counters = WritebackCounters()
    path = str(image_path or "").strip()
    if not path:
        counters.skipped += 1
        return counters

    image_col = (
        (config.get("paths") or {}).get("image_column")
        or config.get("image_column")
        or ""
    )
    if not image_col:
        counters.skipped += 1
        return counters

    table = _quote_ident(config["table"])
    col = _quote_ident(image_col)
    sql = f"INSERT INTO {table} ({col}) VALUES (%s)"
    alias = _resolve_alias(config)
    database = config.get("database")
    try:
        with db_alias_session(alias, database=database) as session_alias:
            conn = connections[session_alias]
            with conn.cursor() as cursor:
                cursor.execute(sql, [path])
            counters.updated += 1
    except (PathWritebackError, ExternalDbError) as exc:
        counters.failed += 1
        counters.errors.append(f"{path}: {exc}"[:240])
        logger.warning("path writeback insert failed: %s", exc)
    except Exception as exc:
        counters.failed += 1
        counters.errors.append(f"{path}: {exc}"[:240])
        logger.warning("path writeback insert failed path=%s: %s", path, exc, exc_info=True)
    return counters


def writeback_image_paths(config: dict | None, image_paths: list[str]) -> WritebackCounters:
    """INSERT one row per image path."""
    total = WritebackCounters()
    if not config:
        return total
    for path in image_paths:
        total.merge(insert_image_path_row(config, image_path=path))
    return total


# Backward-compatible aliases used by older call sites / tests.
def writeback_side_paths(
    config: dict,
    *,
    person_id: str = "",
    finger_position: str = "",
    image_path: str | None = None,
    template_paths: dict[str, str] | None = None,
) -> WritebackCounters:
    """Deprecated: inserts a row for image_path only (ignores match keys / templates)."""
    del person_id, finger_position, template_paths
    return insert_image_path_row(config, image_path=image_path or "")


def writeback_pair_paths(
    config: dict | None,
    *,
    finger_position: str = "",
    sides: list[dict[str, Any]] | None = None,
) -> WritebackCounters:
    """Deprecated: inserts one row per side image_path."""
    del finger_position
    paths = [str(s.get("image_path") or "") for s in (sides or [])]
    return writeback_image_paths(config, paths)
