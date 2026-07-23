"""Diagnose migration status for a source table/view (e.g. v_AFISFilterResult_Image).

Usage on Machine A:

  docker compose -f docker-compose.app.yml -f docker-compose.app.override.yml exec backend \\
    python manage.py diagnose_blob_migration --table v_AFISFilterResult_Image
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q


class Command(BaseCommand):
    help = "Print migration source / job / map stats for a table or view name."

    def add_arguments(self, parser):
        parser.add_argument(
            "--table",
            required=True,
            help="source_table / view name, e.g. v_AFISFilterResult_Image",
        )
        parser.add_argument("--limit-jobs", type=int, default=15)

    def handle(self, *args, **options):
        from images.blob_migration_service import count_migration_candidates, prepare_migration_source
        from images.models import BlobMigrationJob, BlobMigrationSource, BlobTableView, ImageSourceMap
        from images.source_map_service import count_live_map_entries_for_source, lookup_tables_for_source

        table = str(options["table"]).strip()
        job_limit = int(options["limit_jobs"])

        self.stdout.write(f"=== diagnose: {table} ===")

        views = list(
            BlobTableView.objects.filter(source_table=table).order_by("-id").values(
                "id",
                "name",
                "db_alias",
                "database_name",
                "source_object_type",
                "source_pk_column",
                "blob_column",
                "blob_columns",
                "path_lookup_table",
                "source_uid",
            )
        )
        self.stdout.write(f"\n[blob_table_view] count={len(views)}")
        for row in views:
            self.stdout.write(f"  {row}")

        sources = list(BlobMigrationSource.objects.filter(source_table=table).order_by("-id"))
        # also match by path_lookup / storage containing name
        extra = list(
            BlobMigrationSource.objects.filter(
                Q(path_lookup_table=table) | Q(source_table__icontains=table.replace("v_", "", 1))
            )
            .exclude(source_table=table)
            .order_by("-id")[:20]
        )
        self.stdout.write(f"\n[blob_migration_source exact] count={len(sources)}")
        for src in sources:
            self._print_source(src, count_migration_candidates, prepare_migration_source, count_live_map_entries_for_source, lookup_tables_for_source)

        if extra:
            self.stdout.write(f"\n[blob_migration_source related] count={len(extra)}")
            for src in extra:
                self._print_source(src, count_migration_candidates, prepare_migration_source, count_live_map_entries_for_source, lookup_tables_for_source)

        source_ids = [s.id for s in sources] or [s.id for s in extra]
        jobs = (
            BlobMigrationJob.objects.filter(source_id__in=source_ids).order_by("-id")[:job_limit]
            if source_ids
            else BlobMigrationJob.objects.filter(
                Q(source__source_table=table) | Q(message__icontains=table)
            ).order_by("-id")[:job_limit]
        )
        self.stdout.write(f"\n[blob_migration_job] showing up to {job_limit}")
        for job in jobs:
            self.stdout.write(
                f"  id={job.id} source_id={job.source_id} status={job.status} "
                f"processed={job.processed}/{job.total_estimate} "
                f"ok={job.succeeded} skip={job.skipped} fail={job.failed} "
                f"msg={job.message!r} err={job.last_error!r}"
            )

        # Map counts by source_table name variants
        variants = {table, table.lstrip("v_"), table.replace("v_", "", 1)}
        if table.lower().startswith("v_"):
            variants.add(table[2:])
        self.stdout.write("\n[image_source_map live counts by source_table]")
        from images.models import ImageInfo

        live = ImageInfo.objects.filter(is_delete=0).values("id")
        for name in sorted(variants):
            if not name:
                continue
            n = ImageSourceMap.objects.filter(source_table=name, image_info_id__in=live).count()
            self.stdout.write(f"  {name}: {n}")

        self.stdout.write("\nDone.")

    def _print_source(self, src, count_fn, prepare_fn, live_fn, lookup_fn):
        try:
            src = prepare_fn(src)
        except Exception as exc:
            self.stdout.write(f"  id={src.id} prepare_failed: {exc}")
            return
        try:
            tables = lookup_fn(src)
        except Exception as exc:
            tables = [f"<err {exc}>"]
        try:
            stats = count_fn(src.id, use_cache=False)
        except Exception as exc:
            stats = {"error": str(exc)}
        try:
            live = live_fn(src)
        except Exception as exc:
            live = f"<err {exc}>"
        self.stdout.write(
            f"  id={src.id} uid={getattr(src, 'source_uid', '')!r} "
            f"db={src.db_alias}/{src.database_name} type={src.source_object_type} "
            f"pk={src.source_pk_column} blobs={src.blob_columns!r} "
            f"path_lookup={src.path_lookup_table!r} mappings={getattr(src, 'blob_column_path_mappings', '')!r}"
        )
        self.stdout.write(f"    lookup_tables={tables} live_maps={live}")
        self.stdout.write(f"    stats={stats}")
