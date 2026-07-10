"""Pause migration jobs left in running state after a container restart."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from images.blob_migration_job_service import reclaim_orphaned_migration_jobs


class Command(BaseCommand):
    help = "Mark orphaned running blob_migration_job rows as paused (safe after container restart)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reason",
            default="服务重启，已自动暂停",
            help="Message stored on reclaimed jobs",
        )

    def handle(self, *args, **options):
        count = reclaim_orphaned_migration_jobs(reason=(options.get("reason") or "").strip())
        if count:
            self.stdout.write(self.style.SUCCESS(f"Reclaimed {count} orphaned migration job(s)"))
        else:
            self.stdout.write("No orphaned running migration jobs")
