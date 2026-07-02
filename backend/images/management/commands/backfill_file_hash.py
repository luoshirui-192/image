"""Backfill empty file_hash from on-disk upload files."""
from __future__ import annotations

import hashlib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from images.models import ImageInfo
from utils.path_builder import resolve_upload_file


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
        qs = ImageInfo.objects.filter(is_delete=0, file_hash="").order_by("id")
        total = qs.count()
        updated = 0
        missing = 0

        self.stdout.write(f"Found {total} active rows with empty file_hash")

        for record in qs.iterator():
            try:
                abs_path = resolve_upload_file(settings.UPLOAD_ROOT, record.image_path)
            except ValueError:
                missing += 1
                self.stderr.write(f"skip id={record.id} invalid path {record.image_path}")
                continue

            if not abs_path.is_file():
                missing += 1
                self.stderr.write(f"skip id={record.id} file not found {abs_path}")
                continue

            content_hash = hashlib.sha256(abs_path.read_bytes()).hexdigest()
            if dry_run:
                self.stdout.write(f"would update id={record.id} {record.image_name} -> {content_hash[:12]}...")
            else:
                ImageInfo.objects.filter(pk=record.pk).update(file_hash=content_hash)
            updated += 1

        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} {updated} rows; skipped {missing}"))
