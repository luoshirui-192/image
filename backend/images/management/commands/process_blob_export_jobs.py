"""Process pending simulated export jobs (scheduler / cron)."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from images.blob_simulated_export_job_service import process_pending_export_jobs


class Command(BaseCommand):
    help = (
        "Run pending blob_simulated_export_job rows synchronously "
        "(safe for long exports inside the scheduler container)."
    )

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
            help="Maximum jobs to run per invocation (default: 1)",
        )
        parser.add_argument(
            "--stale-seconds",
            type=int,
            default=300,
            help="Reclaim RUNNING jobs with no progress for this many seconds",
        )

    def handle(self, *args, **options):
        count = process_pending_export_jobs(
            max_jobs=max(1, options["max_jobs"]),
            stale_seconds=max(30, options["stale_seconds"]),
        )
        if count:
            self.stdout.write(self.style.SUCCESS(f"Processed {count} export job(s)"))
        else:
            self.stdout.write("No pending export jobs")
