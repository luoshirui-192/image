"""CLI: migrate BLOB columns from legacy tables to upload/."""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from images.blob_migration_service import (
    BlobMigrationError,
    count_migration_candidates,
    create_migration_source,
    run_blob_migration,
)
from images.models import BlobMigrationSource


class Command(BaseCommand):
    help = "Migrate image BLOB data from legacy tables into upload/ and image_info."

    def add_arguments(self, parser):
        parser.add_argument("--source-id", type=int, help="Existing blob_migration_source.id")
        parser.add_argument("--list", action="store_true", help="List migration sources")
        parser.add_argument("--stats", action="store_true", help="Show stats for --source-id")
        parser.add_argument("--source-table", type=str, help="Create/run using source table name")
        parser.add_argument("--blob-column", type=str, help="BLOB column name")
        parser.add_argument("--pk-column", type=str, default="id", help="Primary key column")
        parser.add_argument("--name-column", type=str, default="", help="Optional filename column")
        parser.add_argument("--suffix-column", type=str, default="", help="Optional suffix column")
        parser.add_argument("--category-id", type=int, help="Target image_category.id")
        parser.add_argument("--db-alias", type=str, default="default", help="Django DB alias")
        parser.add_argument("--where", type=str, default="", help="Extra WHERE clause")
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--no-skip-existing", action="store_true")

    def handle(self, *args, **options):
        if options["list"]:
            self._list_sources()
            return

        source_id = options.get("source_id")
        if not source_id and options.get("source_table") and options.get("blob_column"):
            if not options.get("category_id"):
                raise CommandError("--category-id is required when creating a new source")
            source = create_migration_source(
                name=f"{options['source_table']}.{options['blob_column']}",
                source_table=options["source_table"],
                source_pk_column=options.get("pk_column") or "id",
                blob_column=options["blob_column"],
                name_column=options.get("name_column") or "",
                suffix_column=options.get("suffix_column") or "",
                category_id=options["category_id"],
                db_alias=options.get("db_alias") or "default",
                where_clause=options.get("where") or "",
            )
            source_id = source.id
            self.stdout.write(self.style.SUCCESS(f"Created migration source id={source_id}"))

        if not source_id:
            raise CommandError("Specify --source-id or (--source-table, --blob-column, --category-id)")

        if options["stats"]:
            stats = count_migration_candidates(source_id)
            self.stdout.write(str(stats))
            return

        try:
            result = run_blob_migration(
                source_id,
                batch_size=options["batch_size"],
                dry_run=options["dry_run"],
                skip_existing=not options["no_skip_existing"],
                upload_user="migration",
            )
        except BlobMigrationError as exc:
            raise CommandError(str(exc)) from exc

        verb = "Dry-run" if result.dry_run else "Migrated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: processed={result.processed} ok={result.succeeded} "
                f"skip={result.skipped} fail={result.failed}"
            )
        )
        for item in result.items:
            if item.success:
                line = f"  id={item.source_id} file={item.filename}"
                if item.skipped:
                    line += " (skipped)"
                elif item.image_info_id:
                    line += f" -> image_info={item.image_info_id}"
                self.stdout.write(line)
            else:
                self.stderr.write(f"  id={item.source_id} ERROR: {item.error}")

    def _list_sources(self):
        sources = BlobMigrationSource.objects.all().order_by("-id")
        if not sources:
            self.stdout.write("No migration sources configured.")
            return
        for source in sources:
            last_run = source.last_run_at.isoformat() if source.last_run_at else "-"
            self.stdout.write(
                f"id={source.id} table={source.source_table} blob={source.blob_column} "
                f"db={source.db_alias} last_run={last_run}"
            )
