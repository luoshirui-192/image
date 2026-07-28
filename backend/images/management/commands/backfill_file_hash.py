"""Backfill empty file_hash from stored upload files."""
from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand

from images.models import ImageInfo
from utils.storage import get_image_storage


class Command(BaseCommand):
    help = "Compute SHA256 file_hash for image_info rows missing hash (duplicate detection)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report rows that would be updated",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        storage = get_image_storage()
        qs = ImageInfo.objects.filter(is_delete=0, file_hash="").order_by("id")
        total = qs.count()
        updated = 0
        missing = 0

        self.stdout.write(f"Found {total} active rows with empty file_hash")

        for record in qs.iterator():
            if not storage.exists(record.image_path):
                missing += 1
                self.stderr.write(f"skip id={record.id} file not found {record.image_path}")
                continue

            content_hash = hashlib.sha256(storage.read_bytes(record.image_path)).hexdigest()
            if dry_run:
                self.stdout.write(f"would update id={record.id} {record.image_name} -> {content_hash[:12]}...")
            else:
                ImageInfo.objects.filter(pk=record.pk).update(file_hash=content_hash)
            updated += 1

        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} {updated} rows; skipped {missing}"))
