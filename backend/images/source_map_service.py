"""image_source_map queries keyed by logical source_uid with legacy fallback."""
from __future__ import annotations

from django.conf import settings
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from images.blob_schema_helpers import map_storage_table, parse_blob_columns
from images.models import BlobMigrationSource, ImageInfo, ImageSourceMap
from images.source_identity import ensure_source_record_uid, is_valid_source_uid, normalize_source_uid


def legacy_map_lookup_enabled() -> bool:
    return bool(getattr(settings, "BLOB_MAP_LEGACY_LOOKUP", True))


def ensure_migration_source_uid(source: BlobMigrationSource) -> str:
    return ensure_source_record_uid(source, persist=True)


def _live_image_subquery():
    return ImageInfo.objects.filter(is_delete=0).values("id")


def lookup_tables_for_source(source: BlobMigrationSource) -> list[str]:
    from images.blob_schema_helpers import map_storage_table, parse_blob_column_path_mappings

    tables: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        value = (name or "").strip()
        if value and value not in seen:
            seen.add(value)
            tables.append(value)

    try:
        add(
            map_storage_table(
                source_table=source.source_table,
                source_object_type=source.source_object_type,
                path_lookup_table=source.path_lookup_table,
            )
        )
    except ValueError:
        pass
    add(source.source_table)
    for mapping in parse_blob_column_path_mappings(source.blob_column_path_mappings):
        add(mapping.get("lookup_table"))
    return tables


def map_queryset_for_source(
    source: BlobMigrationSource,
    *,
    source_ids: list[str] | None = None,
    columns: list[str] | None = None,
) -> QuerySet[ImageSourceMap]:
    """Return map rows for a migration source; prefer source_uid when set."""
    uid = normalize_source_uid(getattr(source, "source_uid", ""))
    qs = ImageSourceMap.objects.filter(image_info_id__in=_live_image_subquery())

    if is_valid_source_uid(uid):
        scoped = qs.filter(source_uid=uid)
        if scoped.exists() or not legacy_map_lookup_enabled():
            qs = scoped
        else:
            tables = lookup_tables_for_source(source)
            qs = qs.filter(
                Q(source_uid="") | Q(source_uid__isnull=True),
                source_table__in=tables,
            )
    else:
        tables = lookup_tables_for_source(source)
        qs = qs.filter(source_table__in=tables)

    if source_ids:
        qs = qs.filter(source_id__in=[str(item) for item in source_ids])
    if columns:
        cols = list(columns)
        if len(cols) == 1:
            cols.append("")
        qs = qs.filter(source_column__in=cols)
    return qs


def map_queryset_for_uid(
    source_uid: str,
    *,
    lookup_tables: list[str] | None = None,
    source_ids: list[str] | None = None,
    columns: list[str] | None = None,
) -> QuerySet[ImageSourceMap]:
    uid = normalize_source_uid(source_uid)
    qs = ImageSourceMap.objects.filter(image_info_id__in=_live_image_subquery())
    if is_valid_source_uid(uid):
        # Prefer uid-scoped maps, but also keep legacy rows for the same lookup
        # tables. Otherwise a view that inherited a source_uid can miss older maps
        # that still have empty source_uid (common after path-table export).
        if lookup_tables and legacy_map_lookup_enabled():
            qs = qs.filter(
                Q(source_uid=uid)
                | (
                    (Q(source_uid="") | Q(source_uid__isnull=True))
                    & Q(source_table__in=lookup_tables)
                )
            )
        else:
            qs = qs.filter(source_uid=uid)
    elif lookup_tables and legacy_map_lookup_enabled():
        qs = qs.filter(source_table__in=lookup_tables)
    else:
        return qs.none()

    if source_ids:
        qs = qs.filter(source_id__in=[str(item) for item in source_ids])
    if columns:
        cols = list(columns)
        if len(cols) == 1:
            cols.append("")
        qs = qs.filter(source_column__in=cols)
    return qs


def upsert_source_map(
    *,
    source: BlobMigrationSource,
    lookup_table: str,
    map_source_id: str,
    map_column: str,
    image_info_id: int,
) -> ImageSourceMap:
    uid = ensure_migration_source_uid(source)
    table = (lookup_table or "").strip()
    column = (map_column or "").strip()
    defaults = {
        "image_info_id": image_info_id,
        "migrated_at": timezone.now(),
        "source_table": table,
        "migration_source_id": source.pk,
    }

    if is_valid_source_uid(uid):
        row, _ = ImageSourceMap.objects.update_or_create(
            source_uid=uid,
            source_id=str(map_source_id),
            source_column=column,
            defaults=defaults,
        )
        return row

    row, _ = ImageSourceMap.objects.update_or_create(
        source_table=table,
        source_id=str(map_source_id),
        source_column=column,
        defaults={
            "image_info_id": image_info_id,
            "migrated_at": timezone.now(),
            "migration_source_id": source.pk,
        },
    )
    return row


def count_live_map_entries_for_source(source: BlobMigrationSource) -> int:
    blob_cols = parse_blob_columns(source.blob_columns, source.blob_column)
    qs = map_queryset_for_source(source)
    if blob_cols:
        cols = list(blob_cols)
        if len(cols) == 1:
            cols.append("")
        qs = qs.filter(source_column__in=cols)
    return int(qs.aggregate(total=Count("id"))["total"] or 0)


def count_live_map_entries_by_source_uid() -> dict[str, int]:
    from django.db.models import Count

    rows = (
        ImageSourceMap.objects.filter(image_info_id__in=_live_image_subquery())
        .exclude(source_uid="")
        .values("source_uid")
        .annotate(count=Count("id"))
    )
    return {
        str(row["source_uid"]): int(row["count"])
        for row in rows
        if (row.get("source_uid") or "").strip()
    }


def migrated_key_set_for_batch(
    source: BlobMigrationSource,
    *,
    lookup_table: str,
    source_ids: list[str],
    map_columns: list[str],
) -> set[tuple[str, str, str]]:
    """Return (lookup_table, source_id, map_column) keys already migrated."""
    cols = list(map_columns)
    if len(cols) == 1:
        cols.append("")

    uid = normalize_source_uid(getattr(source, "source_uid", ""))
    keys: set[tuple[str, str, str]] = set()
    base = ImageSourceMap.objects.filter(
        source_id__in=[str(item) for item in source_ids],
        image_info_id__in=_live_image_subquery(),
    )
    if cols:
        base = base.filter(source_column__in=cols)

    if is_valid_source_uid(uid):
        rows = base.filter(source_uid=uid)
        if not rows.exists() and legacy_map_lookup_enabled():
            rows = base.filter(Q(source_uid="") | Q(source_uid__isnull=True), source_table=lookup_table)
    else:
        rows = base.filter(source_table=lookup_table)

    for source_id, source_column in rows.values_list("source_id", "source_column"):
        col = (source_column or "").strip()
        if col:
            keys.add((lookup_table, str(source_id), col))
        elif len(map_columns) == 1:
            keys.add((lookup_table, str(source_id), map_columns[0]))
    return keys
