"""Resolve remote table context for image_source_map sync rows."""
from __future__ import annotations

from dataclasses import dataclass

from images.blob_schema_helpers import map_storage_table, parse_blob_column_path_mappings, parse_blob_columns
from images.models import BlobMigrationSource, BlobTableView, ExternalDbConnection


@dataclass(frozen=True)
class TableSyncContext:
    lookup_table: str
    source_column: str
    pk_column: str
    db_alias: str
    database_name: str
    migration_source_id: int | None
    blob_column: str
    source_uid: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return self.lookup_table, self.source_column or ""


def _source_lookup_tables(source: BlobMigrationSource) -> set[str]:
    tables: set[str] = set()
    try:
        tables.add(map_storage_table(
            source_table=source.source_table,
            source_object_type=source.source_object_type,
            path_lookup_table=source.path_lookup_table,
        ))
    except ValueError:
        pass
    tables.add((source.source_table or "").strip())
    for mapping in parse_blob_column_path_mappings(source.blob_column_path_mappings):
        lookup = (mapping.get("lookup_table") or "").strip()
        if lookup:
            tables.add(lookup)
    return {t for t in tables if t}


def _view_lookup_tables(view: BlobTableView) -> set[str]:
    tables: set[str] = set()
    manual = (view.path_lookup_table or "").strip()
    if manual:
        tables.add(manual)
    tables.add((view.source_table or "").strip())
    for mapping in parse_blob_column_path_mappings(view.blob_column_path_mappings):
        lookup = (mapping.get("lookup_table") or "").strip()
        if lookup:
            tables.add(lookup)
    return {t for t in tables if t}


def _fallback_external_db() -> tuple[str, str]:
    record = ExternalDbConnection.objects.filter(enabled=1).order_by("id").first()
    if record is None:
        return "default", ""
    return f"external_{record.id}", (record.db_name or "").strip()


def build_sync_context_index() -> dict[tuple[str, str], TableSyncContext]:
    """Map (lookup_table, source_column) -> how to read remote BLOB fingerprints."""
    index: dict[tuple[str, str], TableSyncContext] = {}

    def put(ctx: TableSyncContext) -> None:
        key = ctx.key
        if key not in index:
            index[key] = ctx

    for source in BlobMigrationSource.objects.filter(enabled=1).order_by("id"):
        db_name = (getattr(source, "database_name", "") or "").strip()
        blob_cols = parse_blob_columns(source.blob_columns, source.blob_column)
        lookup_tables = _source_lookup_tables(source)
        source_uid = (getattr(source, "source_uid", "") or "").strip()
        for lookup_table in lookup_tables:
            for blob_col in blob_cols:
                col = blob_col
                for mapping in parse_blob_column_path_mappings(source.blob_column_path_mappings):
                    if mapping.get("lookup_table") == lookup_table:
                        col = mapping.get("source_column") or mapping.get("view_column") or blob_col
                put(
                    TableSyncContext(
                        lookup_table=lookup_table,
                        source_column=col,
                        pk_column=source.source_pk_column or "id",
                        db_alias=source.db_alias or "default",
                        database_name=db_name,
                        migration_source_id=source.id,
                        blob_column=col,
                        source_uid=source_uid,
                    )
                )
                put(
                    TableSyncContext(
                        lookup_table=lookup_table,
                        source_column="",
                        pk_column=source.source_pk_column or "id",
                        db_alias=source.db_alias or "default",
                        database_name=db_name,
                        migration_source_id=source.id,
                        blob_column=blob_cols[0] if blob_cols else source.blob_column,
                        source_uid=source_uid,
                    )
                )

    for view in BlobTableView.objects.all().order_by("id"):
        db_name = (view.database_name or "").strip()
        blob_cols = parse_blob_columns(view.blob_columns, view.blob_column)
        view_uid = (getattr(view, "source_uid", "") or "").strip()
        for lookup_table in _view_lookup_tables(view):
            for blob_col in blob_cols:
                put(
                    TableSyncContext(
                        lookup_table=lookup_table,
                        source_column=blob_col,
                        pk_column=view.source_pk_column or "id",
                        db_alias=view.db_alias or "default",
                        database_name=db_name,
                        migration_source_id=None,
                        blob_column=blob_col,
                        source_uid=view_uid,
                    )
                )

    db_alias, db_name = _fallback_external_db()
    if db_alias != "default" or db_name:
        from images.models import ImageSourceMap

        pairs = (
            ImageSourceMap.objects.values_list("source_table", "source_column")
            .distinct()
        )
        for lookup_table, source_column in pairs:
            key = (lookup_table, source_column or "")
            if key in index or (lookup_table, "") in index:
                continue
            col = (source_column or "").strip()
            put(
                TableSyncContext(
                    lookup_table=lookup_table,
                    source_column=col,
                    pk_column="id",
                    db_alias=db_alias,
                    database_name=db_name,
                    migration_source_id=None,
                    blob_column=col or "image_data",
                )
            )

    return index


def resolve_sync_context(
    lookup_table: str,
    source_column: str,
    *,
    source_uid: str = "",
    index: dict[tuple[str, str], TableSyncContext] | None = None,
) -> TableSyncContext | None:
    from images.source_identity import is_valid_source_uid, normalize_source_uid

    idx = index if index is not None else build_sync_context_index()
    col = (source_column or "").strip()
    uid = normalize_source_uid(source_uid)
    if is_valid_source_uid(uid):
        for ctx in idx.values():
            if normalize_source_uid(getattr(ctx, "source_uid", "")) == uid:
                if ctx.source_column == col or (not col and not ctx.source_column):
                    return ctx
                if not col and ctx.source_column:
                    return ctx
    if (lookup_table, col) in idx:
        return idx[(lookup_table, col)]
    if (lookup_table, "") in idx:
        return idx[(lookup_table, "")]
    return None
