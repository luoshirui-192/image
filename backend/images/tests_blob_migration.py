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
    count_migration_candidates,
    create_migration_source,
    prepare_migration_source,
    run_blob_migration,
)
from images.models import BlobMigrationJob, BlobMigrationSource, BlobTableView, ImageInfo, ImageSourceMap
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
    create_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS image_source_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table VARCHAR(64) NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    source_column VARCHAR(64) NOT NULL DEFAULT '',
    image_info_id INTEGER NOT NULL,
    migrated_at DATETIME NOT NULL,
    UNIQUE(source_table, source_id, source_column)
);
CREATE TABLE IF NOT EXISTS blob_table_view (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL DEFAULT '',
    db_alias VARCHAR(32) NOT NULL DEFAULT 'default',
    database_name VARCHAR(64) NOT NULL DEFAULT '',
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
        self.assertIn("源表无", finished.message)

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

    @override_settings(UPLOAD_ROOT=None)
    def test_api_create_migration_job(self):
        upload_root = str(self.upload_root)
        self.client.force_authenticate(user=self.admin)
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
