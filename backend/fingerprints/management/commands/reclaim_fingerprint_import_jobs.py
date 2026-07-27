"""Re-queue fingerprint import jobs left in running state after a container restart."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from fingerprints.job_service import kick_pending_import_jobs, reclaim_orphaned_import_jobs


class Command(BaseCommand):
    help = (
        "Re-queue orphaned running fingerprint_import_job rows as pending "
        "(safe after container/worker restart)."
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
            help="Only reclaim; do not start pending import workers",
        )
        parser.add_argument(
            "--kick-limit",
            type=int,
            default=5,
            help="Max pending jobs to kick after reclaim (default 5)",
        )

    def handle(self, *args, **options):
        count = reclaim_orphaned_import_jobs(reason=(options.get("reason") or "").strip())
        if count:
            self.stdout.write(self.style.SUCCESS(f"Reclaimed {count} orphaned fingerprint import job(s)"))
        else:
            self.stdout.write("No orphaned running fingerprint import jobs")
        if not options.get("no_kick"):
            kicked = kick_pending_import_jobs(limit=int(options.get("kick_limit") or 5))
            self.stdout.write(self.style.SUCCESS(f"kicked_fingerprint_import={kicked or 0}"))
