"""Tests for BLOB migration service and API."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from images.blob_migration_job_service import create_migration_job, execute_migration_job, serialize_migration_job
from images.blob_migration_service import (
    _prepare_migration_batch,
    count_migration_candidates,
    create_migration_source,
    find_migration_source_match,
    prepare_migration_source,
    run_blob_migration,
)
from images.models import (
    BlobMigrationJob,
    BlobMigrationJobError,
    BlobMigrationSource,
    BlobTableView,
    ImageInfo,
    ImageSourceMap,
)
from users.models import SysUser

SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS sys_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    password VARCHAR(128) NOT NULL,
    username VARCHAR(100) NOT NULL UNIQUE,
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    status SMALLINT NOT NULL DEFAULT 1,
    create_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS operate_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NULL,
    username VARCHAR(100) NOT NULL DEFAULT '',
    action_type VARCHAR(20) NOT NULL DEFAULT '',
    sql_content TEXT NULL,
    detail VARCHAR(500) NOT NULL DEFAULT '',
    ip VARCHAR(50) NOT NULL DEFAULT '',
    create_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS image_category (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name VARCHAR(100) NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0,
    create_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS image_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_name VARCHAR(255) NOT NULL DEFAULT '',
    image_path VARCHAR(500) NOT NULL DEFAULT '',
    image_width INTEGER NOT NULL DEFAULT 0,
    image_height INTEGER NOT NULL DEFAULT 0,
    file_size INTEGER NOT NULL DEFAULT 0,
    file_suffix VARCHAR(20) NOT NULL DEFAULT '',
    file_hash VARCHAR(64) NOT NULL DEFAULT '',
    upload_time DATETIME NOT NULL,
    update_time DATETIME NOT NULL,
    upload_user VARCHAR(100) NOT NULL DEFAULT '',
    is_delete SMALLINT NOT NULL DEFAULT 0,
    category_id INTEGER NULL,
    tags VARCHAR(500) NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS blob_migration_source (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL DEFAULT '',
    source_table VARCHAR(64) NOT NULL,
    source_pk_column VARCHAR(64) NOT NULL DEFAULT 'id',
    blob_column VARCHAR(64) NOT NULL,
    blob_columns TEXT NOT NULL DEFAULT '',
    source_object_type VARCHAR(20) NOT NULL DEFAULT 'table',
    path_lookup_table VARCHAR(64) NOT NULL DEFAULT '',
    blob_column_path_mappings TEXT NOT NULL DEFAULT '',
    name_column VARCHAR(64) NOT NULL DEFAULT '',
    suffix_column VARCHAR(64) NOT NULL DEFAULT '',
    category_id INTEGER NOT NULL,
    upload_user VARCHAR(100) NOT NULL DEFAULT 'migration',
    tags VARCHAR(500) NOT NULL DEFAULT '',
    where_clause VARCHAR(500) NOT NULL DEFAULT '',
    db_alias VARCHAR(32) NOT NULL DEFAULT 'default',
    database_name VARCHAR(64) NOT NULL DEFAULT '',
    enabled SMALLINT NOT NULL DEFAULT 1,
    last_run_at DATETIME NULL,
    auto_sync_enabled SMALLINT NOT NULL DEFAULT 1,
    sync_interval_minutes INTEGER NOT NULL DEFAULT 60,
    sync_batch_size INTEGER NOT NULL DEFAULT 200,
    sync_last_run_at DATETIME NULL,
    sync_last_checked_map_id INTEGER NOT NULL DEFAULT 0,
    change_track_column VARCHAR(64) NOT NULL DEFAULT '',
    change_track_mode VARCHAR(20) NOT NULL DEFAULT 'hash',
    source_uid VARCHAR(36) NOT NULL DEFAULT '',
    create_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS image_source_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table VARCHAR(64) NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    source_column VARCHAR(64) NOT NULL DEFAULT '',
    image_info_id INTEGER NOT NULL,
    migrated_at DATETIME NOT NULL,
    source_content_hash VARCHAR(64) NOT NULL DEFAULT '',
    source_blob_length INTEGER NOT NULL DEFAULT 0,
    last_checked_at DATETIME NULL,
    sync_status VARCHAR(20) NOT NULL DEFAULT 'unknown',
    last_sync_error VARCHAR(500) NOT NULL DEFAULT '',
    source_uid VARCHAR(36) NOT NULL DEFAULT '',
    migration_source_id INTEGER NULL,
    UNIQUE(source_table, source_id, source_column)
);
CREATE TABLE IF NOT EXISTS blob_table_view (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL DEFAULT '',
    db_alias VARCHAR(32) NOT NULL DEFAULT 'default',
    database_name VARCHAR(64) NOT NULL DEFAULT '',
    source_uid VARCHAR(36) NOT NULL DEFAULT '',
    source_table VARCHAR(64) NOT NULL,
    source_object_type VARCHAR(20) NOT NULL DEFAULT 'table',
    path_lookup_table VARCHAR(64) NOT NULL DEFAULT '',
    blob_column_path_mappings TEXT NOT NULL DEFAULT '',
    source_pk_column VARCHAR(64) NOT NULL DEFAULT 'id',
    blob_column VARCHAR(64) NOT NULL,
    blob_columns TEXT NOT NULL DEFAULT '',
    display_columns TEXT NOT NULL DEFAULT '',
    where_clause VARCHAR(500) NOT NULL DEFAULT '',
    remark VARCHAR(500) NOT NULL DEFAULT '',
    last_viewed_at DATETIME NULL,
    create_time DATETIME NULL,
    update_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS legacy_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title VARCHAR(100) NOT NULL DEFAULT '',
    photo BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS legacy_dual_blob (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title VARCHAR(100) NOT NULL DEFAULT '',
    photo BLOB NOT NULL,
    thumb BLOB NOT NULL
);
CREATE VIEW IF NOT EXISTS legacy_photos_v AS
    SELECT id, title, photo FROM legacy_photos;
CREATE TABLE IF NOT EXISTS join_main (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ara_name VARCHAR(64) NOT NULL,
    match_name VARCHAR(64) NOT NULL
);
CREATE TABLE IF NOT EXISTS join_images (
    fname VARCHAR(64) PRIMARY KEY,
    image_data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS join_faces (
    file_name VARCHAR(64) PRIMARY KEY,
    image_content BLOB NOT NULL
);
CREATE VIEW IF NOT EXISTS join_view AS
    SELECT
        m.id AS id,
        m.ara_name AS ara_name,
        m.match_name AS match_name,
        i.image_data AS image_data,
        f.image_content AS image_content
    FROM join_main m
    JOIN join_images i ON i.fname = m.ara_name
    JOIN join_faces f ON f.file_name = m.match_name;
CREATE TABLE IF NOT EXISTS blob_migration_job (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    dry_run SMALLINT NOT NULL DEFAULT 0,
    skip_existing SMALLINT NOT NULL DEFAULT 1,
    run_all SMALLINT NOT NULL DEFAULT 1,
    retry_failed_only SMALLINT NOT NULL DEFAULT 0,
    parent_job_id INTEGER NULL,
    batch_size INTEGER NOT NULL DEFAULT 50,
    warm_thumbs_after SMALLINT NOT NULL DEFAULT 0,
    cancel_requested SMALLINT NOT NULL DEFAULT 0,
    pause_requested SMALLINT NOT NULL DEFAULT 0,
    total_estimate INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    succeeded INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    last_pk_cursor VARCHAR(128) NOT NULL DEFAULT '',
    message VARCHAR(500) NOT NULL DEFAULT '',
    created_by VARCHAR(100) NOT NULL DEFAULT '',
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    updated_at DATETIME NULL,
    create_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS blob_migration_job_error (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    source_pk VARCHAR(128) NOT NULL DEFAULT '',
    source_column VARCHAR(64) NOT NULL DEFAULT '',
    filename VARCHAR(255) NOT NULL DEFAULT '',
    error_message VARCHAR(1000) NOT NULL DEFAULT '',
    retried SMALLINT NOT NULL DEFAULT 0,
    create_time DATETIME NULL
);
"""


def make_png_bytes(color=(10, 20, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 6), color=color).save(buf, format="PNG")
    return buf.getvalue()


class BlobMigrationTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls.upload_root = Path(cls._temp_dir.name) / "upload"
        cls.upload_root.mkdir(parents=True)
        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_TABLES)

    @classmethod
    def tearDownClass(cls):
        cls._temp_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient()
        self.admin = SysUser.objects.create(
            username="blob_admin",
            password=make_password("admin123"),
            role="admin",
            status=1,
        )
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM legacy_photos")
            cursor.execute("DELETE FROM blob_table_view")
            cursor.execute("DELETE FROM blob_migration_job_error")
            cursor.execute("DELETE FROM blob_migration_job")
            cursor.execute("DELETE FROM image_source_map")
            cursor.execute("DELETE FROM blob_migration_source")
            cursor.execute("DELETE FROM image_info")
            cursor.execute("DELETE FROM image_category")
            cursor.execute(
                "INSERT INTO image_category (id, category_name, sort) VALUES (1, '默认', 0)"
            )
            png = make_png_bytes()
            cursor.execute(
                "INSERT INTO legacy_photos (title, photo) VALUES (?, ?)",
                ["sample.png", png],
            )

        self.source = BlobMigrationSource.objects.create(
            name="legacy test",
            source_table="legacy_photos",
            source_pk_column="id",
            blob_column="photo",
            name_column="title",
            category_id=1,
            upload_user="migration",
            db_alias="default",
            enabled=1,
        )

    @override_settings(UPLOAD_ROOT=None)
    def test_prepare_migration_source_backfills_database_from_table_view(self):
        BlobTableView.objects.create(
            name="browse cfg",
            db_alias="default",
            database_name="legacy_catalog_db",
            source_table="legacy_photos",
            source_pk_column="id",
            blob_column="photo",
            create_time=timezone.now(),
        )
        source = BlobMigrationSource.objects.create(
            name="no db name",
            source_table="legacy_photos",
            source_pk_column="id",
            blob_column="photo",
            category_id=1,
            db_alias="default",
            database_name="",
            enabled=1,
        )
        prepared = prepare_migration_source(source)
        self.assertEqual(prepared.database_name, "legacy_catalog_db")
        source.refresh_from_db()
        self.assertEqual(source.database_name, "legacy_catalog_db")

    @override_settings(UPLOAD_ROOT=None)
    def test_prepare_migration_source_skips_ambiguous_multi_database_views(self):
        now = timezone.now()
        for db_name in ("db_a", "db_b"):
            BlobTableView.objects.create(
                name=f"browse {db_name}",
                db_alias="default",
                database_name=db_name,
                source_table="shared_photos",
                source_pk_column="id",
                blob_column="photo",
                create_time=now,
            )
        source = BlobMigrationSource.objects.create(
            name="ambiguous db",
            source_table="shared_photos",
            source_pk_column="id",
            blob_column="photo",
            category_id=1,
            db_alias="default",
            database_name="",
            enabled=1,
        )
        prepared = prepare_migration_source(source, persist=False)
        self.assertEqual(prepared.database_name, "")

    @override_settings(UPLOAD_ROOT=None)
    def test_find_migration_source_match_requires_database_when_ambiguous(self):
        now = timezone.now()
        BlobMigrationSource.objects.create(
            name="db a",
            source_table="shared_photos",
            source_pk_column="id",
            blob_column="photo",
            category_id=1,
            db_alias="default",
            database_name="db_a",
            enabled=1,
            create_time=now,
        )
        BlobMigrationSource.objects.create(
            name="db b",
            source_table="shared_photos",
            source_pk_column="id",
            blob_column="photo",
            category_id=1,
            db_alias="default",
            database_name="db_b",
            enabled=1,
            create_time=now,
        )

        matched, ambiguous = find_migration_source_match(
            db_alias="default",
            database="db_a",
            source_table="shared_photos",
        )
        self.assertFalse(ambiguous)
        self.assertEqual(matched.database_name, "db_a")

        other, ambiguous_other = find_migration_source_match(
            db_alias="default",
            database="db_b",
            source_table="shared_photos",
        )
        self.assertFalse(ambiguous_other)
        self.assertEqual(other.database_name, "db_b")

        missing, ambiguous_missing = find_migration_source_match(
            db_alias="default",
            database="db_c",
            source_table="shared_photos",
        )
        self.assertFalse(ambiguous_missing)
        self.assertIsNone(missing)

        loose, ambiguous_loose = find_migration_source_match(
            db_alias="default",
            database="",
            source_table="shared_photos",
        )
        self.assertTrue(ambiguous_loose)
        self.assertIsNone(loose)

    @override_settings(UPLOAD_ROOT=None)
    def test_orphan_source_map_does_not_skip_migration(self):
        """Stale image_source_map without live image_info must not block migration."""
        upload_root = str(self.upload_root)
        ImageSourceMap.objects.create(
            source_table="legacy_photos",
            source_id="1",
            source_column="photo",
            image_info_id=99999,
            migrated_at=timezone.now(),
        )
        stats = count_migration_candidates(self.source.id)
        self.assertGreater(stats["pending"], 0)

        with override_settings(UPLOAD_ROOT=upload_root):
            result = run_blob_migration(self.source.id, batch_size=10, dry_run=False, skip_existing=True)
            self.assertEqual(result.succeeded, 1)
            self.assertEqual(ImageInfo.objects.filter(is_delete=0).count(), 1)

    @override_settings(UPLOAD_ROOT=None, BLOB_MIGRATION_UPLOAD_WORKERS=1)
    def test_empty_blob_scan_fails_job(self):
        source = BlobMigrationSource.objects.create(
            name="empty filter",
            source_table="legacy_photos",
            source_pk_column="id",
            blob_column="photo",
            category_id=1,
            db_alias="default",
            where_clause="1=0",
            enabled=1,
        )
        job = create_migration_job(source_id=source.id, created_by="blob_admin", batch_size=10, run_all=True)
        finished = execute_migration_job(job.id)
        self.assertEqual(finished.status, BlobMigrationJob.STATUS_FAILED)
        self.assertIn("源表", finished.message)

    @override_settings(UPLOAD_ROOT=None)
    def test_run_blob_migration_writes_file_and_map(self):
        upload_root = str(self.upload_root)
        with override_settings(UPLOAD_ROOT=upload_root):
            result = run_blob_migration(self.source.id, batch_size=10, dry_run=False)
            self.assertEqual(result.succeeded, 1)
            self.assertEqual(ImageSourceMap.objects.count(), 1)
            self.assertEqual(ImageInfo.objects.filter(is_delete=0).count(), 1)

            mapping = ImageSourceMap.objects.first()
            self.assertEqual(mapping.source_table, "legacy_photos")
            self.assertEqual(mapping.source_id, "1")

            info = ImageInfo.objects.get(pk=mapping.image_info_id)
            file_path = self.upload_root / info.image_path.replace("upload/", "", 1)
            self.assertTrue(file_path.is_file())

            stats = count_migration_candidates(self.source.id)
            self.assertEqual(stats["pending"], 0)

    @override_settings(UPLOAD_ROOT=None)
    def test_multi_blob_migration_creates_two_maps(self):
        upload_root = str(self.upload_root)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM legacy_dual_blob")
            cursor.execute(
                "INSERT INTO legacy_dual_blob (title, photo, thumb) VALUES (?, ?, ?)",
                ["dual.png", make_png_bytes(), make_png_bytes((40, 50, 60))],
            )

        source = create_migration_source(
            name="dual blob",
            source_table="legacy_dual_blob",
            source_pk_column="id",
            blob_columns=["photo", "thumb"],
            category_id=1,
            db_alias="default",
        )

        with override_settings(UPLOAD_ROOT=upload_root):
            result = run_blob_migration(source.id, batch_size=10, dry_run=False)
            self.assertEqual(result.succeeded, 2)
            self.assertEqual(ImageSourceMap.objects.filter(source_table="legacy_dual_blob").count(), 2)
            columns = set(
                ImageSourceMap.objects.filter(source_table="legacy_dual_blob").values_list(
                    "source_column", flat=True
                )
            )
            self.assertEqual(columns, {"photo", "thumb"})

            stats = count_migration_candidates(source.id)
            self.assertEqual(stats["pending"], 0)
            self.assertEqual(stats["total_with_blob"], 2)

    @override_settings(UPLOAD_ROOT=None)
    def test_view_migration_maps_to_lookup_table(self):
        upload_root = str(self.upload_root)
        with override_settings(UPLOAD_ROOT=upload_root):
            source = create_migration_source(
                name="view migrate",
                source_table="legacy_photos_v",
                source_pk_column="id",
                blob_column="photo",
                source_object_type="view",
                path_lookup_table="legacy_photos",
                category_id=1,
                db_alias="default",
            )
            result = run_blob_migration(source.id, batch_size=10, dry_run=False)
            self.assertEqual(result.succeeded, 1)
            mapping = ImageSourceMap.objects.get(source_table="legacy_photos", source_id="1")
            self.assertEqual(mapping.source_column, "photo")

    @override_settings(UPLOAD_ROOT=None)
    def test_join_view_migration_maps_per_base_table(self):
        upload_root = str(self.upload_root)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM join_faces")
            cursor.execute("DELETE FROM join_images")
            cursor.execute("DELETE FROM join_main")
            cursor.execute(
                "INSERT INTO join_images (fname, image_data) VALUES (?, ?)",
                ["ara-1", make_png_bytes()],
            )
            cursor.execute(
                "INSERT INTO join_faces (file_name, image_content) VALUES (?, ?)",
                ["match-1", make_png_bytes((10, 20, 30))],
            )
            cursor.execute(
                "INSERT INTO join_main (ara_name, match_name) VALUES (?, ?)",
                ["ara-1", "match-1"],
            )

        source = create_migration_source(
            name="join view migrate",
            source_table="join_view",
            source_pk_column="id",
            blob_columns=["image_data", "image_content"],
            source_object_type="view",
            path_lookup_table="join_images",
            blob_column_path_mappings=[
                {
                    "view_column": "image_data",
                    "lookup_table": "join_images",
                    "source_id_column": "ara_name",
                    "source_column": "image_data",
                },
                {
                    "view_column": "image_content",
                    "lookup_table": "join_faces",
                    "source_id_column": "match_name",
                    "source_column": "image_content",
                },
            ],
            category_id=1,
            db_alias="default",
        )

        with override_settings(UPLOAD_ROOT=upload_root):
            result = run_blob_migration(source.id, batch_size=10, dry_run=False)
            self.assertEqual(result.succeeded, 2)
            self.assertTrue(
                ImageSourceMap.objects.filter(
                    source_table="join_images",
                    source_id="ara-1",
                    source_column="image_data",
                ).exists()
            )
            self.assertTrue(
                ImageSourceMap.objects.filter(
                    source_table="join_faces",
                    source_id="match-1",
                    source_column="image_content",
                ).exists()
            )
            stats = count_migration_candidates(source.id)
            self.assertEqual(stats["pending"], 0)

            # Re-run should skip both columns via per-base-table maps.
            second = run_blob_migration(source.id, batch_size=10, dry_run=False, skip_existing=True)
            self.assertEqual(second.skipped, 2)
            self.assertEqual(second.succeeded, 0)

    @override_settings(UPLOAD_ROOT=None)
    def test_skip_existing_on_rerun(self):
        upload_root = str(self.upload_root)
        with override_settings(UPLOAD_ROOT=upload_root):
            first = run_blob_migration(self.source.id, batch_size=10, dry_run=False)
            self.assertEqual(first.succeeded, 1)
            second = run_blob_migration(self.source.id, batch_size=10, dry_run=False, skip_existing=True)
            self.assertEqual(second.skipped, 1)
            self.assertEqual(second.succeeded, 0)
            self.assertEqual(ImageInfo.objects.filter(is_delete=0).count(), 1)

    @override_settings(
        UPLOAD_ROOT=None,
        BLOB_MIGRATION_SKIP_SCAN_WINDOW=3,
        BLOB_MIGRATION_SKIP_SCAN_MAX_PER_BATCH=20,
    )
    def test_skip_existing_scan_jumps_to_pending_rows(self):
        """skip_existing should scan past migrated PKs until it fills a pending batch."""
        upload_root = str(self.upload_root)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM legacy_photos")
            for i in range(1, 9):
                cursor.execute(
                    "INSERT INTO legacy_photos (id, title, photo) VALUES (?, ?, ?)",
                    [i, f"p{i}.png", make_png_bytes((i * 10, 20, 30))],
                )

        with override_settings(UPLOAD_ROOT=upload_root):
            # Migrate ids 1..6 so a resume must jump over them to reach 7..8.
            first = run_blob_migration(self.source.id, batch_size=10, dry_run=False)
            self.assertEqual(first.succeeded, 8)

            ImageSourceMap.objects.filter(source_id__in=["7", "8"]).delete()
            self.assertEqual(ImageSourceMap.objects.filter(source_table="legacy_photos").count(), 6)

            prepared = _prepare_migration_batch(
                self.source,
                after_pk="",
                batch_size=2,
                skip_existing=True,
            )
            self.assertEqual(prepared.last_pk, "8")
            self.assertEqual(len(prepared.blob_rows), 2)
            self.assertEqual({str(r["id"]) for r in prepared.blob_rows}, {"7", "8"})
            self.assertGreaterEqual(len(prepared.pre_skipped), 6)

            second = run_blob_migration(self.source.id, batch_size=2, dry_run=False, skip_existing=True)
            self.assertEqual(second.succeeded, 2)
            self.assertGreaterEqual(second.skipped, 6)
            self.assertEqual(ImageSourceMap.objects.filter(source_table="legacy_photos").count(), 8)

    @override_settings(UPLOAD_ROOT=None)
    def test_map_stats_api(self):
        now = timezone.now()
        image = ImageInfo.objects.create(
            image_name="mapped.png",
            image_path="2026/01/mapped.png",
            upload_time=now,
            update_time=now,
            upload_user="test",
            is_delete=0,
        )
        ImageSourceMap.objects.create(
            source_table="legacy_photos",
            source_id="1",
            source_column="photo",
            image_info_id=image.id,
            migrated_at=now,
        )
        self.client.force_authenticate(user=self.admin)
        res = self.client.get("/api/images/blob-migration/map-stats/")
        self.assertEqual(res.status_code, 200)
        counts = res.json()["data"]["by_source_table"]
        self.assertEqual(counts["legacy_photos"], 1)
        self.assertEqual(res.json()["data"].get("by_source_uid"), {})

    @override_settings(UPLOAD_ROOT=None)
    def test_skip_existing_by_source_uid_after_table_move(self):
        upload_root = str(self.upload_root)
        uid = "11111111-1111-4111-8111-111111111111"
        now = timezone.now()
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS legacy_photos_moved ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, title VARCHAR(100), photo BLOB)"
            )
            cursor.execute(
                "INSERT INTO legacy_photos_moved (id, title, photo) "
                "SELECT id, title, photo FROM legacy_photos"
            )
        BlobMigrationSource.objects.filter(pk=self.source.pk).update(
            source_uid=uid,
            source_table="legacy_photos_moved",
        )
        self.source.refresh_from_db()
        image = ImageInfo.objects.create(
            image_name="mapped.png",
            image_path="2026/01/mapped.png",
            upload_time=now,
            update_time=now,
            upload_user="test",
            is_delete=0,
        )
        ImageSourceMap.objects.create(
            source_uid=uid,
            source_table="legacy_photos",
            source_id="1",
            source_column="photo",
            image_info_id=image.id,
            migrated_at=now,
            migration_source_id=self.source.id,
        )
        with override_settings(UPLOAD_ROOT=upload_root):
            result = run_blob_migration(self.source.id, batch_size=10, dry_run=False, skip_existing=True)
            self.assertEqual(result.skipped, 1)
            self.assertEqual(result.succeeded, 0)
            self.assertEqual(ImageInfo.objects.filter(is_delete=0).count(), 1)

    @override_settings(UPLOAD_ROOT=None)
    def test_upsert_updates_legacy_map_when_source_has_uid(self):
        """uk_source is (table,id,column); upsert must not insert a second row for same key."""
        from images.source_map_service import upsert_source_map

        upload_root = str(self.upload_root)
        uid = "33333333-3333-4333-8333-333333333333"
        now = timezone.now()
        BlobMigrationSource.objects.filter(pk=self.source.pk).update(source_uid=uid)
        self.source.refresh_from_db()
        image = ImageInfo.objects.create(
            image_name="legacy.png",
            image_path="2026/01/legacy.png",
            upload_time=now,
            update_time=now,
            upload_user="test",
            is_delete=0,
        )
        ImageSourceMap.objects.create(
            source_uid="",
            source_table="legacy_photos",
            source_id="1",
            source_column="photo",
            image_info_id=image.id,
            migrated_at=now,
        )
        new_image = ImageInfo.objects.create(
            image_name="new.png",
            image_path="2026/01/new.png",
            upload_time=now,
            update_time=now,
            upload_user="test",
            is_delete=0,
        )
        with override_settings(UPLOAD_ROOT=upload_root):
            row = upsert_source_map(
                source=self.source,
                lookup_table="legacy_photos",
                map_source_id="1",
                map_column="photo",
                image_info_id=new_image.id,
            )
        self.assertEqual(row.source_uid, uid)
        self.assertEqual(row.image_info_id, new_image.id)
        self.assertEqual(
            ImageSourceMap.objects.filter(
                source_table="legacy_photos",
                source_id="1",
                source_column="photo",
            ).count(),
            1,
        )

    @override_settings(UPLOAD_ROOT=None)
    def test_find_migration_source_match_by_source_uid(self):
        uid = "22222222-2222-4222-8222-222222222222"
        now = timezone.now()
        source = BlobMigrationSource.objects.create(
            name="uid source",
            source_table="legacy_photos",
            source_pk_column="id",
            blob_column="photo",
            category_id=1,
            db_alias="default",
            database_name="other_db",
            source_uid=uid,
            enabled=1,
            create_time=now,
        )
        matched, ambiguous = find_migration_source_match(
            db_alias="default",
            database="db_a",
            source_table="different_table",
            source_uid=uid,
        )
        self.assertFalse(ambiguous)
        self.assertEqual(matched.id, source.id)

    @override_settings(UPLOAD_ROOT=None)
    def test_api_discover_and_dry_run(self):
        upload_root = str(self.upload_root)
        self.client.force_authenticate(user=self.admin)

        res = self.client.post("/api/images/blob-migration/discover/", {"db_alias": "default"}, format="json")
        self.assertEqual(res.status_code, 200)
        tables = res.json()["data"]["tables"]
        self.assertTrue(any(t["table"] == "legacy_photos" for t in tables))

        with override_settings(UPLOAD_ROOT=upload_root):
            res = self.client.post(
                "/api/images/blob-migration/run/",
                {"source_id": self.source.id, "batch_size": 5, "dry_run": True},
                format="json",
            )
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["data"]["succeeded"], 1)
            self.assertEqual(ImageInfo.objects.count(), 0)

    @override_settings(UPLOAD_ROOT=None, BLOB_MIGRATION_UPLOAD_WORKERS=1)
    def test_rerun_job_completes_when_nothing_pending(self):
        upload_root = str(self.upload_root)
        with override_settings(UPLOAD_ROOT=upload_root):
            first = run_blob_migration(self.source.id, batch_size=10, dry_run=False)
            self.assertEqual(first.succeeded, 1)

            job = create_migration_job(
                source_id=self.source.id,
                created_by="blob_admin",
                batch_size=10,
                run_all=True,
                skip_existing=True,
            )
            self.assertEqual(job.total_estimate, 0)
            finished = execute_migration_job(job.id)
            self.assertEqual(finished.status, BlobMigrationJob.STATUS_COMPLETED)
            # Already migrated: cursor walk skips existing rows (no new successes).
            self.assertEqual(finished.succeeded, 0)
            self.assertGreaterEqual(finished.skipped, 1)

    @override_settings(UPLOAD_ROOT=None, BLOB_MIGRATION_UPLOAD_WORKERS=1)
    def test_migration_job_runs_to_completion(self):
        upload_root = str(self.upload_root)
        with override_settings(UPLOAD_ROOT=upload_root):
            job = create_migration_job(
                source_id=self.source.id,
                created_by="blob_admin",
                batch_size=10,
                run_all=True,
            )
            finished = execute_migration_job(job.id)
            self.assertEqual(finished.status, BlobMigrationJob.STATUS_COMPLETED)
            self.assertEqual(finished.succeeded, 1)
            payload = serialize_migration_job(finished)
            self.assertEqual(payload["percent"], 100.0)

    @override_settings(UPLOAD_ROOT=None, BLOB_MIGRATION_UPLOAD_WORKERS=1)
    def test_retry_failed_job_batch_migrates_and_marks_retried(self):
        upload_root = str(self.upload_root)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM legacy_photos")
            for i, color in enumerate([(10, 20, 30), (40, 50, 60), (70, 80, 90)], start=1):
                cursor.execute(
                    "INSERT INTO legacy_photos (id, title, photo) VALUES (?, ?, ?)",
                    [i, f"r{i}.png", make_png_bytes(color)],
                )

        parent = create_migration_job(
            source_id=self.source.id,
            created_by="blob_admin",
            batch_size=10,
            run_all=True,
            warm_thumbs_after=False,
        )
        BlobMigrationJob.objects.filter(pk=parent.pk).update(
            status=BlobMigrationJob.STATUS_CANCELLED,
            failed=3,
        )
        now = timezone.now()
        for pk in ("1", "2", "3"):
            BlobMigrationJobError.objects.create(
                job_id=parent.id,
                source_pk=pk,
                source_column="photo",
                filename=f"r{pk}.png",
                error_message="simulated",
                retried=0,
                create_time=now,
            )

        with override_settings(UPLOAD_ROOT=upload_root):
            retry_job = create_migration_job(
                source_id=self.source.id,
                created_by="blob_admin",
                batch_size=2,
                run_all=True,
                skip_existing=False,
                warm_thumbs_after=False,
                retry_failed_only=True,
                parent_job_id=parent.id,
            )
            finished = execute_migration_job(retry_job.id)

        self.assertEqual(finished.status, BlobMigrationJob.STATUS_COMPLETED)
        self.assertEqual(finished.succeeded, 3)
        self.assertEqual(finished.failed, 0)
        self.assertEqual(
            BlobMigrationJobError.objects.filter(job_id=parent.id, retried=1).count(),
            3,
        )
        self.assertEqual(ImageSourceMap.objects.filter(source_table="legacy_photos").count(), 3)

    @override_settings(UPLOAD_ROOT=None)
    def test_api_create_migration_job(self):
        from unittest.mock import patch

        upload_root = str(self.upload_root)
        self.client.force_authenticate(user=self.admin)
        with patch("images.blob_migration_views.kick_migration_job_async"):
            res = self.client.post(
                "/api/images/blob-migration/jobs/",
                {"source_id": self.source.id, "batch_size": 10, "run_all": True},
                format="json",
            )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["data"]["status"], "pending")

        with override_settings(UPLOAD_ROOT=upload_root, BLOB_MIGRATION_UPLOAD_WORKERS=1):
            job_id = res.json()["data"]["id"]
            execute_migration_job(job_id)
            detail = self.client.get(f"/api/images/blob-migration/jobs/{job_id}/")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["data"]["status"], "completed")

    @override_settings(UPLOAD_ROOT=None)
    def test_api_cancel_pending_job(self):
        self.client.force_authenticate(user=self.admin)
        job = create_migration_job(
            source_id=self.source.id,
            created_by="blob_admin",
            batch_size=10,
            run_all=True,
        )
        res = self.client.post(f"/api/images/blob-migration/jobs/{job.id}/cancel/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"]["status"], "cancelled")
        self.assertTrue(res.json()["data"]["cancel_requested"])

    @override_settings(UPLOAD_ROOT=None)
    def test_api_pause_and_resume_pending_job(self):
        from unittest.mock import patch

        self.client.force_authenticate(user=self.admin)
        job = create_migration_job(
            source_id=self.source.id,
            created_by="blob_admin",
            batch_size=10,
            run_all=True,
        )
        pause_res = self.client.post(f"/api/images/blob-migration/jobs/{job.id}/pause/")
        self.assertEqual(pause_res.status_code, 200)
        self.assertEqual(pause_res.json()["data"]["status"], "paused")

        with patch("images.blob_migration_views.kick_migration_job_async"):
            resume_res = self.client.post(f"/api/images/blob-migration/jobs/{job.id}/resume/")
        self.assertEqual(resume_res.status_code, 200)
        self.assertEqual(resume_res.json()["data"]["status"], "pending")

    @override_settings(UPLOAD_ROOT=None)
    def test_reclaim_orphaned_running_job(self):
        from images.blob_migration_job_service import reclaim_orphaned_migration_jobs

        job = create_migration_job(
            source_id=self.source.id,
            created_by="blob_admin",
            batch_size=10,
            run_all=True,
        )
        BlobMigrationJob.objects.filter(pk=job.id).update(
            status=BlobMigrationJob.STATUS_RUNNING,
            succeeded=10,
            skipped=2,
            processed=12,
        )
        count = reclaim_orphaned_migration_jobs(reason="测试重启")
        self.assertEqual(count, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, BlobMigrationJob.STATUS_PENDING)
        self.assertIn("测试重启", job.message)

    @override_settings(UPLOAD_ROOT=None)
    def test_api_delete_finished_job(self):
        self.client.force_authenticate(user=self.admin)
        job = create_migration_job(
            source_id=self.source.id,
            created_by="blob_admin",
            batch_size=10,
            run_all=True,
        )
        BlobMigrationJob.objects.filter(pk=job.id).update(
            status=BlobMigrationJob.STATUS_COMPLETED,
            finished_at=timezone.now(),
        )
        res = self.client.delete(f"/api/images/blob-migration/jobs/{job.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(BlobMigrationJob.objects.filter(pk=job.id).exists())

    @override_settings(UPLOAD_ROOT=None)
    def test_api_delete_running_job_force(self):
        self.client.force_authenticate(user=self.admin)
        job = create_migration_job(
            source_id=self.source.id,
            created_by="blob_admin",
            batch_size=10,
            run_all=True,
        )
        BlobMigrationJob.objects.filter(pk=job.id).update(status=BlobMigrationJob.STATUS_RUNNING)
        res = self.client.delete(f"/api/images/blob-migration/jobs/{job.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(BlobMigrationJob.objects.filter(pk=job.id).exists())

    @override_settings(UPLOAD_ROOT=None)
    def test_api_clear_job_history(self):
        self.client.force_authenticate(user=self.admin)
        finished = create_migration_job(
            source_id=self.source.id,
            created_by="blob_admin",
            batch_size=10,
            run_all=True,
        )
        BlobMigrationJob.objects.filter(pk=finished.id).update(status=BlobMigrationJob.STATUS_COMPLETED)
        running = create_migration_job(
            source_id=self.source.id,
            created_by="blob_admin",
            batch_size=10,
            run_all=True,
        )
        BlobMigrationJob.objects.filter(pk=running.id).update(status=BlobMigrationJob.STATUS_RUNNING)

        res = self.client.post("/api/images/blob-migration/jobs/clear/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"]["deleted"], 2)
        self.assertEqual(BlobMigrationJob.objects.count(), 0)
