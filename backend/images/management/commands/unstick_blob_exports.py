"""Force-requeue stuck export jobs and start the oldest pending one."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from images.blob_simulated_export_job_service import (
    kick_export_queue,
    process_pending_export_jobs,
    reclaim_orphaned_export_jobs,
)
from images.models import BlobSimulatedExportJob
from images.schema_ensure import ensure_blob_export_job_schema


class Command(BaseCommand):
    help = (
        "Unstick export queue: ensure schema, requeue running+paused → pending, "
        "then run the oldest pending job synchronously."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--async-kick",
            action="store_true",
            help="Only spawn a thread (default: run one job synchronously in this process)",
        )

    def handle(self, *args, **options):
        ensure_blob_export_job_schema()
        before = list(
            BlobSimulatedExportJob.objects.order_by("id").values_list("id", "status", "message")[:20]
        )
        self.stdout.write(f"before={before}")

        n = reclaim_orphaned_export_jobs(
            reason="手动解除卡住，已重新排队",
            include_paused=True,
        )
        self.stdout.write(self.style.SUCCESS(f"reclaimed={n}"))

        if options.get("async_kick"):
            kicked = kick_export_queue(reclaim_stale=False)
            self.stdout.write(self.style.SUCCESS(f"kicked={kicked or 0}"))
        else:
            count = process_pending_export_jobs(max_jobs=1, stale_seconds=30)
            self.stdout.write(self.style.SUCCESS(f"processed={count}"))

        after = list(
            BlobSimulatedExportJob.objects.order_by("id").values_list("id", "status", "message")[:20]
        )
        self.stdout.write(f"after={after}")
