"""Remove orphan thumbnail cache files — Step 26."""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from images.file_service import thumb_cache_path
from images.models import ImageInfo


class Command(BaseCommand):
    help = "清理缩略图缓存目录中无对应图片记录或源文件已删除的条目"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="仅统计，不删除文件",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        cache_root = Path(settings.THUMB_CACHE_ROOT)
        if not cache_root.is_dir():
            self.stdout.write("thumb cache 目录不存在，跳过")
            return

        active_paths = set(
            ImageInfo.objects.filter(is_delete=0).values_list("image_path", flat=True)
        )
        expected = {thumb_cache_path(path) for path in active_paths if path}

        removed = 0
        freed = 0
        for cache_file in cache_root.glob("*.jpg"):
            if cache_file in expected:
                continue
            try:
                size = cache_file.stat().st_size
            except OSError:
                continue
            if not dry_run:
                cache_file.unlink(missing_ok=True)
            removed += 1
            freed += size

        prefix = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}removed={removed} bytes_freed={freed} expected_active={len(expected)}"
            )
        )
