"""Rebind logical sources to new physical locations; schema drift checks."""
from __future__ import annotations

from django.db import connections
from django.utils import timezone

from images.blob_migration_service import BlobMigrationError, _load_source, _validate_source_config, validate_db_alias
from images.blob_schema_helpers import parse_blob_columns
from images.blob_sync_detect import list_remote_column_names
from images.blob_view_path_service import BlobViewPathError, resolve_source_metadata
from images.external_db_service import db_alias_session
from images.models import BlobMigrationSource, BlobTableView
from images.source_identity import ensure_source_record_uid, normalize_source_uid


class SourceRebindError(Exception):
    pass


def detect_schema_drift(source: BlobMigrationSource) -> dict:
    """Compare remote table columns with migration source configuration."""
    from images.blob_migration_service import prepare_migration_source

    source = prepare_migration_source(source, persist=False)
    issues: list[dict] = []
    blob_cols = set(parse_blob_columns(source.blob_columns, source.blob_column))
    pk = (source.source_pk_column or "id").strip().lower()

    try:
        with db_alias_session(source.db_alias, database=(source.database_name or None)) as alias:
            conn = connections[alias]
            remote = {name.lower(): name for name in list_remote_column_names(conn, source.source_table)}
    except Exception as exc:
        return {
            "ok": False,
            "level": "error",
            "issues": [{"level": "error", "code": "connection_failed", "message": str(exc)}],
        }

    if pk not in remote:
        issues.append(
            {
                "level": "error",
                "code": "pk_missing",
                "message": f"主键列 {source.source_pk_column} 在远程表中不存在",
            }
        )

    for col in sorted(blob_cols):
        if col.lower() not in remote:
            issues.append(
                {
                    "level": "error",
                    "code": "blob_column_missing",
                    "message": f"BLOB 列 {col} 在远程表中不存在",
                }
            )

    configured_lower = {c.lower() for c in blob_cols}
    for name in remote.values():
        lower = name.lower()
        if lower in {"blob", "tinyblob", "mediumblob", "longblob", "binary", "varbinary"}:
            continue
        if lower.endswith("_blob") or lower in {"photo", "image", "img", "picture", "thumb", "thumbnail"}:
            if lower not in configured_lower and name not in blob_cols:
                issues.append(
                    {
                        "level": "warn",
                        "code": "blob_column_new",
                        "message": f"发现未配置的 BLOB 列 {name}",
                        "column": name,
                    }
                )

    level = "ok"
    if any(item["level"] == "error" for item in issues):
        level = "error"
    elif issues:
        level = "warn"

    return {
        "ok": level == "ok",
        "level": level,
        "source_uid": normalize_source_uid(getattr(source, "source_uid", "")),
        "db_alias": source.db_alias,
        "database_name": source.database_name,
        "source_table": source.source_table,
        "issues": issues,
    }


def rebind_migration_source(
    source_id: int,
    *,
    db_alias: str,
    database_name: str,
    source_table: str,
    source_object_type: str | None = None,
    path_lookup_table: str | None = None,
) -> BlobMigrationSource:
    """Point an existing logical source at a new physical table location."""
    source = _load_source(source_id)
    uid = ensure_source_record_uid(source, persist=True)
    alias = validate_db_alias(db_alias)
    table = (source_table or "").strip()
    if not table:
        raise SourceRebindError("source_table 不能为空")

    initial_db = (database_name or "").strip()
    with db_alias_session(alias, database=initial_db or None) as session_alias:
        conn = connections[session_alias]
        db_name = initial_db or str(conn.settings_dict.get("NAME") or "").strip()
        try:
            meta = resolve_source_metadata(
                conn,
                database=db_name,
                object_name=table,
                object_type=source_object_type or source.source_object_type,
                path_lookup_table=path_lookup_table if path_lookup_table is not None else source.path_lookup_table,
                blob_columns=parse_blob_columns(source.blob_columns, source.blob_column),
                blob_column=source.blob_column,
            )
        except BlobViewPathError as exc:
            raise SourceRebindError(str(exc)) from exc

    BlobMigrationSource.objects.filter(pk=source.pk).update(
        db_alias=alias,
        database_name=db_name,
        source_table=table,
        source_object_type=meta["source_object_type"],
        path_lookup_table=meta.get("path_lookup_table") or "",
    )
    source.refresh_from_db()
    source.source_uid = uid
    try:
        _validate_source_config(source)
    except BlobMigrationError as exc:
        raise SourceRebindError(str(exc)) from exc

    drift = detect_schema_drift(source)
    if drift["level"] == "error":
        raise SourceRebindError(
            "；".join(item["message"] for item in drift.get("issues", []) if item.get("level") == "error")
            or "远程表结构校验失败"
        )
    return source


def link_table_view_to_source_uid(view_id: int, source_uid: str) -> BlobTableView:
    uid = normalize_source_uid(source_uid)
    if not uid:
        raise SourceRebindError("source_uid 无效")

    source = BlobMigrationSource.objects.filter(source_uid=uid).order_by("-id").first()
    if source is None:
        raise SourceRebindError(f"未找到 source_uid={uid} 的迁移源")

    try:
        view = BlobTableView.objects.get(pk=view_id)
    except BlobTableView.DoesNotExist as exc:
        raise SourceRebindError("浏览配置不存在") from exc

    BlobTableView.objects.filter(pk=view.pk).update(
        source_uid=uid,
        db_alias=source.db_alias,
        database_name=source.database_name,
        source_table=source.source_table,
        source_object_type=source.source_object_type,
        path_lookup_table=source.path_lookup_table or "",
        update_time=timezone.now(),
    )
    view.refresh_from_db()
    return view
