"""Process pending BLOB migration background jobs (scheduler / cron)."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from images.blob_migration_job_service import process_pending_migration_jobs


class Command(BaseCommand):
    help = "Run pending blob_migration_job rows (background migration worker)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process up to --max-jobs pending jobs then exit",
        )
        parser.add_argument(
            "--max-jobs",
            type=int,
            default=1,
            help="Maximum jobs to start per invocation (default: 1)",
        )
        parser.add_argument(
            "--job-id",
            type=int,
            default=None,
            help="Run a specific job id instead of the oldest pending job",
        )

    def handle(self, *args, **options):
        count = process_pending_migration_jobs(
            max_jobs=max(1, options["max_jobs"]),
            job_id=options.get("job_id"),
        )
        if count:
            self.stdout.write(self.style.SUCCESS(f"Processed {count} migration job(s)"))
        elif options["once"]:
            self.stdout.write("No pending migration jobs")
