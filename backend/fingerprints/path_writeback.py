"""Write fingerprint import paths into ara_fp_analyst business tables.

Fixed targets (machine-A / mysql8039):
  - T_CAP_FP_DATA: cap_image_id + dataset_code + fingerprint_image(path bytes)
  - T_FEATURE_RECORD: fp_image_id(=cap_image_id) + Bidiso/Neuiso paths

Image path format: upload/...
Template path format: templates/...
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.db import connections
from django.utils import timezone

from images.blob_migration_service import BlobMigrationError, validate_identifier
from images.external_db_service import ExternalDbError, db_alias_session, external_alias

logger = logging.getLogger(__name__)

MAX_WRITEBACK_ERRORS = 20

# Fixed business mapping
DEFAULT_DATABASE = "ara_fp_analyst"
DEFAULT_DATASET_CODE = "PK_5W"
CAP_TABLE = "T_CAP_FP_DATA"
FEATURE_TABLE = "T_FEATURE_RECORD"

_SCHEMA_ENSURED: set[str] = set()


class PathWritebackError(Exception):
    """Invalid path write-back configuration."""


@dataclass
class WritebackCounters:
    """`updated` counts successfully written image rows (API compat)."""

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


def _truthy_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_path_writeback_config(raw: Any) -> dict | None:
    """
    Normalize API/job options. Table/column mapping is fixed; only connection matters.

      {
        "enabled": true,
        "connection_id": 3,             # optional
        "db_alias": "default",          # fallback when no connection_id
        "database": "ara_fp_analyst",   # optional override
        "dataset_code": "PK_5W"         # optional override
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

        database_raw = raw.get("database", DEFAULT_DATABASE)
        if database_raw is None or str(database_raw).strip() == "":
            # Empty = do not USE/switch database (connection default / sqlite tests)
            database = ""
        else:
            database = str(database_raw).strip()
            validate_identifier(database, label="数据库名")
        dataset_code = str(raw.get("dataset_code") or DEFAULT_DATASET_CODE).strip() or DEFAULT_DATASET_CODE
        if len(dataset_code) > 32:
            raise PathWritebackError("dataset_code 过长（最多 32）")
    except BlobMigrationError as exc:
        raise PathWritebackError(str(exc)) from exc

    return {
        "enabled": True,
        "connection_id": connection_id,
        "db_alias": db_alias,
        "database": database,
        "dataset_code": dataset_code,
        "cap_table": CAP_TABLE,
        "feature_table": FEATURE_TABLE,
    }


def _resolve_alias(config: dict) -> str:
    if config.get("connection_id") is not None:
        return external_alias(int(config["connection_id"]))
    return str(config.get("db_alias") or "default")


def _new_feature_id() -> str:
    return uuid.uuid4().hex  # 32 chars, fits varchar(32)


def _as_blob_path(path: str) -> bytes:
    """Store relative path string inside LONGBLOB fingerprint_image."""
    return path.encode("utf-8")


def ensure_feature_path_columns(config: dict) -> None:
    """One-time-ish ALTER: int score columns → varchar path columns."""
    alias = _resolve_alias(config)
    database = str(config.get("database") or "").strip()
    cache_key = f"{alias}|{database or '_'}|{FEATURE_TABLE}"
    if cache_key in _SCHEMA_ENSURED:
        return

    with db_alias_session(alias, database=database or None) as session_alias:
        conn = connections[session_alias]
        if conn.vendor != "mysql":
            # Unit tests (sqlite): assume columns already varchar/compatible.
            _SCHEMA_ENSURED.add(cache_key)
            return
        schema = database or str(conn.settings_dict.get("NAME") or "")
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                  AND COLUMN_NAME IN ('feature_ara_data', 'feature_neuro_data')
                """,
                [schema, FEATURE_TABLE],
            )
            rows = {r[0]: (str(r[1] or "").lower(), r[2]) for r in cursor.fetchall()}
            if not rows:
                raise PathWritebackError(
                    f"未找到 {schema}.{FEATURE_TABLE}.feature_ara_data / feature_neuro_data"
                )

            need_alter = False
            for col in ("feature_ara_data", "feature_neuro_data"):
                dtype, maxlen = rows.get(col, ("", None))
                if dtype in {"int", "integer", "bigint", "smallint", "tinyint", "mediumint"}:
                    need_alter = True
                elif dtype in {"varchar", "char"} and (maxlen is None or int(maxlen) < 500):
                    need_alter = True
                elif dtype not in {
                    "varchar",
                    "char",
                    "text",
                    "mediumtext",
                    "longtext",
                    "blob",
                    "longblob",
                }:
                    need_alter = True

            if need_alter:
                logger.warning(
                    "Altering %s.%s feature_ara_data/feature_neuro_data to VARCHAR(500) for path storage",
                    schema,
                    FEATURE_TABLE,
                )
                cursor.execute(
                    f"""
                    ALTER TABLE `{FEATURE_TABLE}`
                      MODIFY COLUMN `feature_ara_data` varchar(500) NULL
                        COMMENT 'ara/Bidiso feature storage path',
                      MODIFY COLUMN `feature_neuro_data` varchar(500) NULL
                        COMMENT 'NEURO/Neuiso feature storage path'
                    """
                )
    _SCHEMA_ENSURED.add(cache_key)


def writeback_cap_and_feature(
    config: dict,
    *,
    cap_image_id: str,
    image_path: str,
    bidiso_path: str | None = None,
    neuiso_path: str | None = None,
    created_by: str = "",
) -> WritebackCounters:
    """
    Insert/update one capture row + linked feature row.

    - T_CAP_FP_DATA.fingerprint_image := utf8 bytes of upload/... path
    - T_FEATURE_RECORD.fp_image_id := cap_image_id
    - feature_ara_data := templates/... Bidiso path (optional)
    - feature_neuro_data := templates/... Neuiso path (optional)
    """
    counters = WritebackCounters()
    cap_image_id = str(cap_image_id or "").strip()
    image_path = str(image_path or "").strip()
    if not cap_image_id or not image_path:
        counters.skipped += 1
        return counters
    if len(cap_image_id) > 256:
        counters.failed += 1
        counters.errors.append(f"{cap_image_id[:40]}…: cap_image_id 过长")
        return counters

    bidiso_path = (bidiso_path or "").strip() or None
    neuiso_path = (neuiso_path or "").strip() or None
    dataset_code = str(config.get("dataset_code") or DEFAULT_DATASET_CODE)[:32]
    created_by = (created_by or "")[:16]
    now = timezone.now()
    if timezone.is_aware(now):
        now = timezone.localtime(now)
    created_time = now.replace(tzinfo=None) if isinstance(now, datetime) else now

    alias = _resolve_alias(config)
    database = str(config.get("database") or "").strip() or None

    try:
        ensure_feature_path_columns(config)
        with db_alias_session(alias, database=database) as session_alias:
            conn = connections[session_alias]
            with conn.cursor() as cursor:
                # Capture row
                cursor.execute(
                    f"SELECT `cap_image_id` FROM `{CAP_TABLE}` WHERE `cap_image_id`=%s LIMIT 1",
                    [cap_image_id],
                )
                exists_cap = cursor.fetchone() is not None
                blob_path = _as_blob_path(image_path)
                if exists_cap:
                    cursor.execute(
                        f"""
                        UPDATE `{CAP_TABLE}`
                        SET `fingerprint_image`=%s,
                            `dataset_code`=%s
                        WHERE `cap_image_id`=%s
                        """,
                        [blob_path, dataset_code, cap_image_id],
                    )
                else:
                    cursor.execute(
                        f"""
                        INSERT INTO `{CAP_TABLE}`
                          (`cap_image_id`, `dataset_code`, `fingerprint_image`,
                           `created_by`, `created_time`)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        [cap_image_id, dataset_code, blob_path, created_by or None, created_time],
                    )

                # Feature row (FK requires cap row first)
                cursor.execute(
                    f"SELECT `fp_feature_id` FROM `{FEATURE_TABLE}` WHERE `fp_image_id`=%s LIMIT 1",
                    [cap_image_id],
                )
                feat_row = cursor.fetchone()
                if feat_row:
                    cursor.execute(
                        f"""
                        UPDATE `{FEATURE_TABLE}`
                        SET `feature_ara_data`=%s,
                            `feature_neuro_data`=%s,
                            `created_by`=COALESCE(`created_by`, %s)
                        WHERE `fp_image_id`=%s
                        """,
                        [bidiso_path, neuiso_path, created_by or None, cap_image_id],
                    )
                else:
                    cursor.execute(
                        f"""
                        INSERT INTO `{FEATURE_TABLE}`
                          (`fp_feature_id`, `fp_image_id`,
                           `feature_ara_data`, `feature_neuro_data`,
                           `created_by`, `created_time`)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        [
                            _new_feature_id(),
                            cap_image_id,
                            bidiso_path,
                            neuiso_path,
                            created_by or None,
                            created_time,
                        ],
                    )
            counters.updated += 1
    except (PathWritebackError, ExternalDbError) as exc:
        counters.failed += 1
        counters.errors.append(f"{cap_image_id}: {exc}"[:240])
        logger.warning("path writeback failed id=%s: %s", cap_image_id, exc)
    except Exception as exc:
        counters.failed += 1
        counters.errors.append(f"{cap_image_id}: {exc}"[:240])
        logger.warning("path writeback failed id=%s: %s", cap_image_id, exc, exc_info=True)
    return counters


def writeback_import_sides(
    config: dict | None,
    sides: list[dict[str, Any]],
    *,
    created_by: str = "",
) -> WritebackCounters:
    """
    Write each imported sample side.

    side dict keys:
      cap_image_id (stem), image_path, bidiso_path?, neuiso_path?
    """
    total = WritebackCounters()
    if not config:
        return total
    for side in sides:
        total.merge(
            writeback_cap_and_feature(
                config,
                cap_image_id=str(side.get("cap_image_id") or ""),
                image_path=str(side.get("image_path") or ""),
                bidiso_path=side.get("bidiso_path"),
                neuiso_path=side.get("neuiso_path"),
                created_by=created_by,
            )
        )
    return total


# ---- Backward-compatible thin wrappers (older tests / call sites) ----

def insert_image_path_row(config: dict, *, image_path: str) -> WritebackCounters:
    """Deprecated wrapper: insert with synthetic id from path basename."""
    from pathlib import Path

    stem = Path(image_path).stem if image_path else ""
    return writeback_cap_and_feature(
        config,
        cap_image_id=stem or uuid.uuid4().hex[:16],
        image_path=image_path,
    )


def writeback_image_paths(config: dict | None, image_paths: list[str]) -> WritebackCounters:
    total = WritebackCounters()
    if not config:
        return total
    for path in image_paths:
        total.merge(insert_image_path_row(config, image_path=path))
    return total
