"""Re-queue migration jobs left in running state after a container restart."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from images.blob_migration_job_service import kick_migration_queue, reclaim_orphaned_migration_jobs


class Command(BaseCommand):
    help = (
        "Re-queue orphaned running blob_migration_job rows as pending "
        "(keeps last_pk_cursor; safe after container restart)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reason",
            default="服务重启，已自动重新排队",
            help="Message stored on reclaimed jobs",
        )
        parser.add_argument(
            "--no-kick",
            action="store_true",
            help="Only reclaim; do not start the next pending migration",
        )

    def handle(self, *args, **options):
        count = reclaim_orphaned_migration_jobs(reason=(options.get("reason") or "").strip())
        if count:
            self.stdout.write(self.style.SUCCESS(f"Reclaimed {count} orphaned migration job(s)"))
        else:
            self.stdout.write("No orphaned running migration jobs")
        if not options.get("no_kick"):
            kicked = kick_migration_queue()
            self.stdout.write(self.style.SUCCESS(f"kicked_migration={kicked or 0}"))
