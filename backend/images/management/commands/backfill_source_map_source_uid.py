"""Backfill source_uid / migration_source_id on image_source_map from migration sources."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q

from images.blob_schema_helpers import parse_blob_columns
from images.models import BlobMigrationSource, ImageSourceMap
from images.source_identity import is_valid_source_uid, normalize_source_uid
from images.source_map_service import lookup_tables_for_source


class Command(BaseCommand):
    help = "Backfill image_source_map.source_uid and migration_source_id from blob_migration_source."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report only; do not write")
        parser.add_argument("--source-id", type=int, default=None, help="Limit to one migration source")
        parser.add_argument("--limit", type=int, default=None, help="Max map rows to scan")

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        source_id = options.get("source_id")
        limit = options.get("limit")

        sources_qs = BlobMigrationSource.objects.all().order_by("id")
        if source_id is not None:
            sources_qs = sources_qs.filter(pk=source_id)

        updated = 0
        skipped = 0
        scanned = 0

        for source in sources_qs:
            uid = normalize_source_uid(getattr(source, "source_uid", ""))
            if not is_valid_source_uid(uid):
                self.stderr.write(f"skip source id={source.id}: missing source_uid")
                continue

            tables = lookup_tables_for_source(source)
            blob_cols = parse_blob_columns(source.blob_columns, source.blob_column)
            cols = list(blob_cols)
            if len(cols) == 1:
                cols.append("")

            qs = ImageSourceMap.objects.filter(
                Q(source_uid="") | Q(source_uid__isnull=True),
                source_table__in=tables,
            )
            if cols:
                qs = qs.filter(source_column__in=cols)
            if limit is not None:
                remaining = max(0, limit - scanned)
                if remaining <= 0:
                    break
                qs = qs[:remaining]

            for row in qs.iterator(chunk_size=500):
                scanned += 1
                if dry_run:
                    updated += 1
                    continue
                ImageSourceMap.objects.filter(pk=row.pk).update(
                    source_uid=uid,
                    migration_source_id=source.id,
                )
                updated += 1

        self.stdout.write(
            f"{'dry-run ' if dry_run else ''}scanned={scanned} updated={updated} skipped_sources={skipped}"
        )
