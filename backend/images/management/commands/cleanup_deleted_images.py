"""Remove physical files for long-deleted image records — Step 16."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from images.maintenance import cleanup_deleted_image_files


class Command(BaseCommand):
    help = "Permanently purge legacy soft-deleted image records past retention period."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Retention days after logical delete (default: DELETED_IMAGE_RETENTION_DAYS)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report actions without deleting files",
        )

    def handle(self, *args, **options):
        result = cleanup_deleted_image_files(
            retention_days=options["days"],
            dry_run=options["dry_run"],
        )
        mode = "DRY-RUN" if options["dry_run"] else "DONE"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] scanned={result.scanned} files_deleted={result.files_deleted} "
                f"thumbs_deleted={result.thumbs_deleted} bytes_freed={result.bytes_freed}"
            )
        )
        for err in result.errors:
            self.stdout.write(self.style.WARNING(err))
