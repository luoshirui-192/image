"""Pre-generate thumbnail cache for active images (speeds up list/preview)."""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from images.file_service import ImageNotFoundError, get_or_create_thumbnail, thumb_cache_path
from images.models import ImageInfo
from utils.storage import get_image_storage


class Command(BaseCommand):
    help = (
        "Warm local thumb_cache by generating thumbnails for active image_info rows. "
        "Safe to re-run; skips entries whose cache is already up to date."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only count candidate rows; do not read MinIO or write cache",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max rows to process (0 = no limit)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Delete existing cache file before regenerating",
        )
        parser.add_argument(
            "--progress-every",
            type=int,
            default=100,
            help="Print progress every N processed rows (default: 100)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = max(0, int(options["limit"] or 0))
        force = options["force"]
        progress_every = max(1, int(options["progress_every"] or 100))

        qs = ImageInfo.objects.filter(is_delete=0).order_by("id")
        total = qs.count()
        if limit:
            self.stdout.write(f"Candidates: {total} active rows (limit {limit})")
        else:
            self.stdout.write(f"Candidates: {total} active rows")

        cache_root = Path(settings.THUMB_CACHE_ROOT)
        self.stdout.write(f"Thumb cache root: {cache_root}")
        self.stdout.write(f"Thumb size: {settings.THUMB_SIZE}px")

        if dry_run:
            cap = limit or total
            self.stdout.write(self.style.SUCCESS(f"Dry-run: would process up to {cap} rows"))
            return

        storage = get_image_storage()
        warmed = 0
        skipped = 0
        failed = 0
        processed = 0

        for record in qs.iterator(chunk_size=200):
            if limit and processed >= limit:
                break
            processed += 1

            cache_file = thumb_cache_path(record.image_path)
            if force and cache_file.is_file():
                cache_file.unlink(missing_ok=True)
            elif cache_file.is_file():
                src_stat = storage.stat(record.image_path)
                if src_stat is not None and cache_file.stat().st_mtime >= src_stat.mtime:
                    skipped += 1
                    if processed % progress_every == 0:
                        self._print_progress(processed, warmed, skipped, failed)
                    continue

            try:
                get_or_create_thumbnail(record.image_path)
                warmed += 1
            except ImageNotFoundError as exc:
                failed += 1
                self.stderr.write(f"skip id={record.id} path={record.image_path}: {exc}")
            except Exception as exc:
                failed += 1
                self.stderr.write(f"fail id={record.id} path={record.image_path}: {exc}")

            if processed % progress_every == 0:
                self._print_progress(processed, warmed, skipped, failed)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: processed={processed} warmed={warmed} "
                f"skipped={skipped} failed={failed}"
            )
        )

    def _print_progress(self, processed: int, warmed: int, skipped: int, failed: int) -> None:
        self.stdout.write(
            f"progress processed={processed} warmed={warmed} "
            f"skipped={skipped} failed={failed}"
        )
