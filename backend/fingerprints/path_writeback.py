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
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.db import close_old_connections, connections, transaction
from django.utils import timezone

from images.blob_migration_service import BlobMigrationError, validate_identifier
from images.external_db_service import ExternalDbError, alias_from_connection_config, db_alias_session, external_alias

logger = logging.getLogger(__name__)

MAX_WRITEBACK_ERRORS = 20

# Fixed business mapping
DEFAULT_DATABASE = "ara_fp_analyst"
DEFAULT_DATASET_CODE = "PK_5W"
CAP_TABLE = "T_CAP_FP_DATA"
FEATURE_TABLE = "T_FEATURE_RECORD"

# Serialize writeback schema ALTER / column probes across parallel import workers.
_WRITEBACK_LOCK = threading.Lock()
_SCHEMA_ENSURED: set[str] = set()
_SCHEMA_FAILED: dict[str, str] = {}
_CAP_HAS_URL_COL: dict[str, bool] = {}


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
    return alias_from_connection_config(config)


def _new_feature_id() -> str:
    return uuid.uuid4().hex  # 32 chars, fits varchar(32)


def _as_blob_path(path: str) -> bytes:
    """Store relative path string inside LONGBLOB fingerprint_image."""
    return path.encode("utf-8")


def normalize_relative_path(path: str | None, *, expect_prefix: str | None = None) -> str:
    """Strip accidental bucket/prefix noise; keep upload/... or templates/..."""
    p = str(path or "").strip().replace("\\", "/")
    if not p:
        return ""
    while p.startswith("/"):
        p = p[1:]
    for junk in ("data/image_db/", "image_db/", "minio/", "bucket/"):
        if p.lower().startswith(junk):
            p = p[len(junk) :]
    if expect_prefix and not p.startswith(expect_prefix):
        # still accept; callers may pass full relative paths with date folders
        pass
    return p


def _schema_cache_key(config: dict) -> str:
    alias = _resolve_alias(config)
    database = str(config.get("database") or "").strip()
    return f"{alias}|{database or '_'}|{FEATURE_TABLE}"


def _probe_feature_columns(cursor, schema: str) -> dict[str, tuple[str, Any]]:
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
    return {r[0]: (str(r[1] or "").lower(), r[2]) for r in cursor.fetchall()}


def _columns_ready_for_paths(rows: dict[str, tuple[str, Any]]) -> bool:
    if not rows or "feature_ara_data" not in rows or "feature_neuro_data" not in rows:
        return False
    ok_types = {"varchar", "char", "text", "mediumtext", "longtext", "blob", "longblob"}
    for col in ("feature_ara_data", "feature_neuro_data"):
        dtype, maxlen = rows[col]
        if dtype in {"int", "integer", "bigint", "smallint", "tinyint", "mediumint"}:
            return False
        if dtype in {"varchar", "char"} and (maxlen is None or int(maxlen) < 500):
            return False
        if dtype not in ok_types:
            return False
    return True


def _cap_has_fingerprint_url(cursor, schema: str, cache_key: str) -> bool:
    if cache_key in _CAP_HAS_URL_COL:
        return _CAP_HAS_URL_COL[cache_key]
    has_url = True
    try:
        if schema:
            cursor.execute(
                """
                SELECT 1 FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = 'fingerprint_url'
                LIMIT 1
                """,
                [schema, CAP_TABLE],
            )
            has_url = cursor.fetchone() is not None
        else:
            # sqlite / no schema: assume present if tests created it
            has_url = True
    except Exception:
        has_url = False
    _CAP_HAS_URL_COL[cache_key] = has_url
    return has_url


def ensure_feature_path_columns(config: dict) -> None:
    """One-time-ish ALTER: int score columns → varchar path columns."""
    cache_key = _schema_cache_key(config)
    if cache_key in _SCHEMA_ENSURED:
        return

    alias = _resolve_alias(config)
    database = str(config.get("database") or "").strip()

    try:
        with db_alias_session(alias, database=database or None) as session_alias:
            conn = connections[session_alias]
            if conn.vendor != "mysql":
                _SCHEMA_ENSURED.add(cache_key)
                _SCHEMA_FAILED.pop(cache_key, None)
                return
            schema = database or str(conn.settings_dict.get("NAME") or "")
            with conn.cursor() as cursor:
                rows = _probe_feature_columns(cursor, schema)
                if not rows:
                    raise PathWritebackError(
                        f"未找到 {schema}.{FEATURE_TABLE}.feature_ara_data / feature_neuro_data"
                    )
                if _columns_ready_for_paths(rows):
                    _SCHEMA_ENSURED.add(cache_key)
                    _SCHEMA_FAILED.pop(cache_key, None)
                    return

                logger.warning(
                    "Altering %s.%s feature_*_data to VARCHAR(500) for path storage",
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
        _SCHEMA_FAILED.pop(cache_key, None)
    except PathWritebackError as exc:
        _SCHEMA_FAILED[cache_key] = str(exc)
        raise
    except Exception as exc:
        # Re-probe: DBA may have altered manually since a previous failure.
        try:
            with db_alias_session(alias, database=database or None) as session_alias:
                conn = connections[session_alias]
                if conn.vendor == "mysql":
                    schema = database or str(conn.settings_dict.get("NAME") or "")
                    with conn.cursor() as cursor:
                        rows = _probe_feature_columns(cursor, schema)
                        if _columns_ready_for_paths(rows):
                            _SCHEMA_ENSURED.add(cache_key)
                            _SCHEMA_FAILED.pop(cache_key, None)
                            return
        except Exception:
            pass
        msg = (
            f"无法调整 {FEATURE_TABLE} 路径列（需 ALTER 权限，"
            f"或手工执行 sql/alter_t_feature_record_path_columns.sql）: {exc}"
        )
        _SCHEMA_FAILED[cache_key] = msg
        raise PathWritebackError(msg) from exc


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
    - T_CAP_FP_DATA.fingerprint_url := same path string when column exists
    - T_FEATURE_RECORD.fp_image_id := cap_image_id
    - feature_ara_data / feature_neuro_data := templates/... paths
      (UPDATE uses COALESCE so missing side does not wipe the other)
    """
    counters = WritebackCounters()
    cap_image_id = str(cap_image_id or "").strip()
    image_path = normalize_relative_path(image_path, expect_prefix="upload/")
    if not cap_image_id or not image_path:
        counters.skipped += 1
        return counters
    if len(cap_image_id) > 256:
        counters.failed += 1
        counters.errors.append(f"{cap_image_id[:40]}…: cap_image_id 过长")
        return counters

    bidiso_path = normalize_relative_path(bidiso_path, expect_prefix="templates/") or None
    neuiso_path = normalize_relative_path(neuiso_path, expect_prefix="templates/") or None
    dataset_code = str(config.get("dataset_code") or DEFAULT_DATASET_CODE)[:32]
    created_by_cap = (created_by or "")[:20]
    created_by_feat = (created_by or "")[:16]
    now = timezone.now()
    if timezone.is_aware(now):
        now = timezone.localtime(now)
    created_time = now.replace(tzinfo=None) if isinstance(now, datetime) else now

    alias = _resolve_alias(config)
    database = str(config.get("database") or "").strip() or None
    url_path = image_path[:256]
    blob_path = _as_blob_path(image_path)
    cache_key = _schema_cache_key(config)

    try:
        close_old_connections()
        with _WRITEBACK_LOCK:
            ensure_feature_path_columns(config)
            with db_alias_session(alias, database=database) as session_alias:
                conn = connections[session_alias]
                schema = (database or str(conn.settings_dict.get("NAME") or "")).strip()
                with transaction.atomic(using=session_alias):
                    with conn.cursor() as cursor:
                        has_url = (
                            _cap_has_fingerprint_url(cursor, schema, cache_key)
                            if conn.vendor == "mysql"
                            else True
                        )

                        cursor.execute(
                            f"SELECT `cap_image_id` FROM `{CAP_TABLE}` WHERE `cap_image_id`=%s LIMIT 1",
                            [cap_image_id],
                        )
                        exists_cap = cursor.fetchone() is not None
                        if exists_cap:
                            if has_url:
                                cursor.execute(
                                    f"""
                                    UPDATE `{CAP_TABLE}`
                                    SET `fingerprint_image`=%s,
                                        `fingerprint_url`=%s,
                                        `dataset_code`=%s
                                    WHERE `cap_image_id`=%s
                                    """,
                                    [blob_path, url_path, dataset_code, cap_image_id],
                                )
                            else:
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
                            if has_url:
                                cursor.execute(
                                    f"""
                                    INSERT INTO `{CAP_TABLE}`
                                      (`cap_image_id`, `dataset_code`, `fingerprint_image`,
                                       `fingerprint_url`, `created_by`, `created_time`)
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                    """,
                                    [
                                        cap_image_id,
                                        dataset_code,
                                        blob_path,
                                        url_path,
                                        created_by_cap or None,
                                        created_time,
                                    ],
                                )
                            else:
                                cursor.execute(
                                    f"""
                                    INSERT INTO `{CAP_TABLE}`
                                      (`cap_image_id`, `dataset_code`, `fingerprint_image`,
                                       `created_by`, `created_time`)
                                    VALUES (%s, %s, %s, %s, %s)
                                    """,
                                    [
                                        cap_image_id,
                                        dataset_code,
                                        blob_path,
                                        created_by_cap or None,
                                        created_time,
                                    ],
                                )

                        # Prefer UPDATE-all by fp_image_id (index is not UNIQUE on prod).
                        # COALESCE keeps existing path when this import lacks that template.
                        cursor.execute(
                            f"""
                            UPDATE `{FEATURE_TABLE}`
                            SET `feature_ara_data`=COALESCE(%s, `feature_ara_data`),
                                `feature_neuro_data`=COALESCE(%s, `feature_neuro_data`),
                                `created_by`=COALESCE(`created_by`, %s)
                            WHERE `fp_image_id`=%s
                            """,
                            [bidiso_path, neuiso_path, created_by_feat or None, cap_image_id],
                        )
                        if cursor.rowcount == 0:
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
                                    created_by_feat or None,
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
    finally:
        close_old_connections()
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
