"""Scheduler worker: detect external BLOB changes and re-migrate."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from images.blob_sync_service import process_due_blob_sync, run_detect_and_resync_for_source


class Command(BaseCommand):
    help = "Process due BLOB sync jobs (detect + optional re-migration)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one pass and exit")
        parser.add_argument("--source-id", type=int, default=None, help="Force sync one source")
        parser.add_argument("--max-sources", type=int, default=1)

    def handle(self, *args, **options):
        source_id = options.get("source_id")
        if source_id:
            result = run_detect_and_resync_for_source(source_id)
            self.stdout.write(
                f"source={source_id} checked={result.checked} changed={result.changed} "
                f"resynced={result.resynced} failed={result.failed}"
            )
            return

        count = process_due_blob_sync(max_sources=int(options.get("max_sources") or 1))
        self.stdout.write(f"processed_sources={count}")
