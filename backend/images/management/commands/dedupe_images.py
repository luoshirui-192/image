"""Remove duplicate image_info rows; keep one record per image_name."""
from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from images.file_service import thumb_cache_path
from images.models import ImageInfo
from utils.storage import StorageStat, get_image_storage


def _score_record(record: ImageInfo, file_stat: StorageStat | None) -> tuple:
    """Higher is better when picking the keeper."""
    has_file = 1 if file_stat is not None else 0
    has_hash = 1 if record.file_hash else 0
    active = 1 if record.is_delete == 0 else 0
    return (active, has_file, has_hash, record.id)


class Command(BaseCommand):
    help = "Deduplicate image_info by image_name; keep best row and remove extras."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report actions without changing database or files",
        )
        parser.add_argument(
            "--restore-kept",
            action="store_true",
            default=True,
            help="Set kept rows to is_delete=0 (default: true)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        restore_kept = options["restore_kept"]
        storage = get_image_storage()

        names = (
            ImageInfo.objects.values_list("image_name", flat=True)
            .distinct()
            .order_by("image_name")
        )

        removed_rows = 0
        removed_files = 0
        kept_rows = 0
        restored_rows = 0

        for name in names:
            records = list(ImageInfo.objects.filter(image_name=name).order_by("id"))
            if not records:
                continue

            scored = []
            for record in records:
                file_stat = storage.stat(record.image_path)
                scored.append((record, file_stat, _score_record(record, file_stat)))

            scored.sort(key=lambda item: item[2], reverse=True)
            keeper, keeper_stat, _ = scored[0]
            extras = scored[1:]

            if not extras:
                if restore_kept and keeper.is_delete != 0:
                    if dry_run:
                        self.stdout.write(f"keep id={keeper.id} {name} (would restore)")
                    else:
                        ImageInfo.objects.filter(pk=keeper.pk).update(is_delete=0)
                    restored_rows += 1
                kept_rows += 1
                continue

            self.stdout.write(
                f"{name}: keep id={keeper.id}, remove {[r.id for r, _, _ in extras]}"
            )

            for record, _file_stat, _ in extras:
                removed_rows += 1
                if dry_run:
                    continue
                if record.image_path != keeper.image_path:
                    deleted, _ = storage.delete(record.image_path)
                    if deleted:
                        removed_files += 1
                    thumb_cache_path(record.image_path).unlink(missing_ok=True)
                record.delete()

            if dry_run:
                kept_rows += 1
                continue

            with transaction.atomic():
                updates = {}
                if restore_kept:
                    updates["is_delete"] = 0
                if keeper_stat and not keeper.file_hash:
                    updates["file_hash"] = hashlib.sha256(
                        storage.read_bytes(keeper.image_path)
                    ).hexdigest()
                if updates:
                    updates["update_time"] = timezone.now()
                    ImageInfo.objects.filter(pk=keeper.pk).update(**updates)
                    if updates.get("is_delete") == 0 and keeper.is_delete != 0:
                        restored_rows += 1
            kept_rows += 1

        verb = "Would process" if dry_run else "Processed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: kept={kept_rows} removed_rows={removed_rows} "
                f"removed_files={removed_files} restored={restored_rows}"
            )
        )
