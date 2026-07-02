"""Run all scheduled maintenance tasks — Step 16."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from images.maintenance import cleanup_deleted_image_files, compute_storage_stats, purge_old_operate_logs


class Command(BaseCommand):
    help = "Run image file cleanup, log purge, and print storage stats."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Dry run for destructive steps")
        parser.add_argument("--image-days", type=int, default=None)
        parser.add_argument("--log-days", type=int, default=None)

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        self.stdout.write("== Cleanup deleted image files ==")
        img_result = cleanup_deleted_image_files(
            retention_days=options["image_days"],
            dry_run=dry_run,
        )
        self.stdout.write(
            f"scanned={img_result.scanned} files_deleted={img_result.files_deleted} "
            f"bytes_freed={img_result.bytes_freed}"
        )

        self.stdout.write("== Purge old operate logs ==")
        log_result = purge_old_operate_logs(
            retention_days=options["log_days"],
            dry_run=dry_run,
        )
        self.stdout.write(f"deleted={log_result['deleted']}")

        self.stdout.write("== Storage stats ==")
        stats = compute_storage_stats()
        self.stdout.write(
            f"active={stats['image_active_count']} deleted={stats['image_deleted_count']} "
            f"upload_disk_bytes={stats['upload_disk_bytes']}"
        )
