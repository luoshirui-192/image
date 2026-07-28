"""Purge old operate_log rows — Step 16."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from images.maintenance import purge_old_operate_logs


class Command(BaseCommand):
    help = "Delete operate_log records older than retention period."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Retention days (default: LOG_RETENTION_DAYS)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count rows only, do not delete",
        )

    def handle(self, *args, **options):
        summary = purge_old_operate_logs(
            retention_days=options["days"],
            dry_run=options["dry_run"],
        )
        mode = "DRY-RUN" if summary["dry_run"] else "DONE"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] retention_days={summary['retention_days']} deleted={summary['deleted']}"
            )
        )
