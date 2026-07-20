from django.core.management.base import BaseCommand

from images.blob_simulated_export_job_service import (
    kick_export_queue,
    reclaim_orphaned_export_jobs,
)


class Command(BaseCommand):
    help = "Reclaim orphaned running export jobs after backend restart, then kick queue"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reason",
            default="服务重启，已自动重新排队",
            help="Message stored on reclaimed jobs",
        )
        parser.add_argument(
            "--no-kick",
            action="store_true",
            help="Only reclaim; do not start the next pending export",
        )

    def handle(self, *args, **options):
        count = reclaim_orphaned_export_jobs(reason=(options.get("reason") or "").strip())
        self.stdout.write(self.style.SUCCESS(f"reclaimed_exports={count}"))
        if not options.get("no_kick"):
            kicked = kick_export_queue()
            self.stdout.write(self.style.SUCCESS(f"kicked_export={kicked or 0}"))
