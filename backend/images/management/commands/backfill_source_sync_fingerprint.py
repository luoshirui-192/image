"""Backfill external BLOB fingerprints on image_source_map."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from images.blob_sync_service import BlobSyncError, backfill_source_sync_fingerprints


class Command(BaseCommand):
    help = "Backfill source_content_hash / sync_status for existing image_source_map rows."

    def add_arguments(self, parser):
        parser.add_argument("--source-id", type=int, default=None, help="Limit to one migration source")
        parser.add_argument("--table", type=str, default=None, help="Limit to one source_table")
        parser.add_argument("--batch-size", type=int, default=None)
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            result = backfill_source_sync_fingerprints(
                source_id=options.get("source_id"),
                lookup_table=options.get("table"),
                batch_size=options.get("batch_size"),
                limit=options.get("limit"),
                dry_run=bool(options.get("dry_run")),
            )
        except BlobSyncError as exc:
            self.stderr.write(str(exc))
            raise SystemExit(1) from exc

        mode = "dry-run" if options.get("dry_run") else "done"
        self.stdout.write(
            f"[{mode}] checked={result.checked} changed={result.changed} failed={result.failed}"
        )
        for err in result.errors[:20]:
            self.stdout.write(f"  error: {err}")
