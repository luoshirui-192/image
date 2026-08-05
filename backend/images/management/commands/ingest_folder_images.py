"""CLI: walk a local folder → MinIO/local storage → image_info.image_path."""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from images.folder_ingest_service import FolderIngestError, ingest_folder_images
from utils.storage import get_image_storage


class Command(BaseCommand):
    help = (
        "遍历本地文件夹中的图片，写入对象存储（STORAGE_BACKEND=minio 时为 MinIO），"
        "并把相对路径写入 image_info.image_path。"
    )

    def add_arguments(self, parser):
        parser.add_argument("root", type=str, help="要遍历的本地文件夹路径")
        parser.add_argument(
            "--upload-user",
            type=str,
            default="folder_ingest",
            help="写入 image_info.upload_user（默认 folder_ingest）",
        )
        parser.add_argument("--category-id", type=int, help="目标 image_category.id")
        parser.add_argument("--tags", type=str, default="", help="标签，写入 image_info.tags")
        parser.add_argument(
            "--no-recursive",
            action="store_true",
            help="只扫描根目录，不递归子文件夹",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="遇到同名/同哈希已存在记录时覆盖文件与元数据",
        )
        parser.add_argument(
            "--no-skip-existing",
            action="store_true",
            help="遇到重复不跳过（默认跳过）；与 --overwrite 互斥时以 overwrite 为准",
        )
        parser.add_argument("--dry-run", action="store_true", help="只枚举图片，不写入存储/数据库")
        parser.add_argument("--limit", type=int, help="最多处理 N 个文件（调试用）")
        parser.add_argument(
            "--verbose-items",
            action="store_true",
            help="逐条打印每个文件的结果",
        )

    def handle(self, *args, **options):
        storage = get_image_storage()
        self.stdout.write(
            f"storage_backend={getattr(storage, 'backend_name', '?')} root={options['root']}"
        )

        try:
            result = ingest_folder_images(
                options["root"],
                upload_user=options["upload_user"],
                category_id=options.get("category_id"),
                tags=options.get("tags") or "",
                recursive=not options["no_recursive"],
                skip_existing=not options["no_skip_existing"],
                overwrite=bool(options["overwrite"]),
                dry_run=bool(options["dry_run"]),
                limit=options.get("limit"),
            )
        except FolderIngestError as exc:
            raise CommandError(str(exc)) from exc

        if options["verbose_items"] or options["dry_run"]:
            for item in result.items:
                if item.skipped:
                    mark = "SKIP"
                elif item.success:
                    mark = "OK"
                else:
                    mark = "FAIL"
                detail = item.image_path or item.error
                self.stdout.write(f"  [{mark}] {item.source_path} -> {detail}")

        verb = "Dry-run" if result.dry_run else "Ingested"
        summary = (
            f"{verb}: found={result.total_found} ok={result.succeeded} "
            f"skip={result.skipped} fail={result.failed} "
            f"backend={result.storage_backend}"
        )
        style = self.style.WARNING if result.failed else self.style.SUCCESS
        self.stdout.write(style(summary))

        if result.failed and not result.dry_run:
            raise CommandError(f"有 {result.failed} 个文件失败")
