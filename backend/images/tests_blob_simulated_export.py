"""Tests for exporting simulated browse rows to another connection table."""
from __future__ import annotations

import io
import tempfile

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from images.blob_simulated_export_service import (
    SimulatedExportError,
    export_simulated_table_to_connection,
)
from images.blob_table_view_service import create_table_view
from images.models import ImageInfo, ImageSourceMap
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
CREATE TABLE IF NOT EXISTS legacy_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title VARCHAR(100) NOT NULL DEFAULT '',
    photo BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS blob_simulated_export_job (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    view_id INTEGER NOT NULL,
    target_connection_id INTEGER NULL,
    target_db_alias VARCHAR(64) NOT NULL DEFAULT '',
    target_database VARCHAR(64) NOT NULL DEFAULT '',
    target_table VARCHAR(64) NOT NULL DEFAULT '',
    if_exists VARCHAR(20) NOT NULL DEFAULT 'fail',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    total_estimate INTEGER NOT NULL DEFAULT 0,
    rows_written INTEGER NOT NULL DEFAULT 0,
    last_offset INTEGER NOT NULL DEFAULT 0,
    cancel_requested SMALLINT NOT NULL DEFAULT 0,
    pause_requested SMALLINT NOT NULL DEFAULT 0,
    message VARCHAR(500) NOT NULL DEFAULT '',
    last_error VARCHAR(500) NOT NULL DEFAULT '',
    result_json TEXT NULL,
    created_by VARCHAR(100) NOT NULL DEFAULT '',
    create_time DATETIME NULL,
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    updated_at DATETIME NULL
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
"""

EXPORT_TABLE = "legacy_photos_path_export"


def make_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


class SimulatedExportTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._temp_dir = tempfile.TemporaryDirectory()
        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_TABLES)

    @classmethod
    def tearDownClass(cls):
        cls._temp_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient()
        self.admin = SysUser.objects.create(
            username="export_admin",
            password=make_password("admin123"),
            role="admin",
            status=1,
        )
        now = timezone.now()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM legacy_photos")
            cursor.execute("DELETE FROM image_source_map")
            cursor.execute("DELETE FROM blob_table_view")
            cursor.execute("DELETE FROM image_info")
            cursor.execute("DELETE FROM blob_simulated_export_job")
            cursor.execute(f"DROP TABLE IF EXISTS {EXPORT_TABLE}")
            png = make_png_bytes()
            cursor.execute(
                "INSERT INTO legacy_photos (id, title, photo) VALUES (1, 'a.png', ?)",
                [png],
            )
            cursor.execute(
                "INSERT INTO legacy_photos (id, title, photo) VALUES (2, 'b.png', ?)",
                [png],
            )

        self.image = ImageInfo.objects.create(
            image_name="a.png",
            image_path="2026/01/a.png",
            image_width=8,
            image_height=6,
            file_size=100,
            file_suffix=".png",
            upload_time=now,
            update_time=now,
            upload_user="test",
            is_delete=0,
        )
        ImageSourceMap.objects.create(
            source_table="legacy_photos",
            source_id="1",
            source_column="photo",
            image_info_id=self.image.id,
            migrated_at=now,
        )
        self.view = create_table_view(
            name="export source",
            db_alias="default",
            source_table="legacy_photos",
            source_pk_column="id",
            blob_column="photo",
        )

    def tearDown(self):
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {EXPORT_TABLE}")
            cursor.execute("DELETE FROM legacy_photos")
            cursor.execute("DELETE FROM image_source_map")
            cursor.execute("DELETE FROM blob_table_view")
            cursor.execute("DELETE FROM image_info")
        super().tearDown()

    def _read_export_rows(self):
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT id, title, photo FROM {EXPORT_TABLE} ORDER BY id"
            )
            return cursor.fetchall()

    def test_export_writes_path_or_empty(self):
        result = export_simulated_table_to_connection(
            self.view.id,
            target_db_alias="default",
            target_table=EXPORT_TABLE,
            if_exists="fail",
        )
        self.assertEqual(result["rows_written"], 2)
        rows = self._read_export_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1], "a.png")
        self.assertEqual(rows[0][2], "2026/01/a.png")
        self.assertEqual(rows[1][1], "b.png")
        self.assertEqual(rows[1][2], "")

    def test_export_fail_when_target_exists(self):
        export_simulated_table_to_connection(
            self.view.id,
            target_db_alias="default",
            target_table=EXPORT_TABLE,
            if_exists="fail",
        )
        with self.assertRaises(SimulatedExportError):
            export_simulated_table_to_connection(
                self.view.id,
                target_db_alias="default",
                target_table=EXPORT_TABLE,
                if_exists="fail",
            )

    def test_export_replace_overwrites(self):
        export_simulated_table_to_connection(
            self.view.id,
            target_db_alias="default",
            target_table=EXPORT_TABLE,
            if_exists="fail",
        )
        result = export_simulated_table_to_connection(
            self.view.id,
            target_db_alias="default",
            target_table=EXPORT_TABLE,
            if_exists="replace",
        )
        self.assertEqual(result["rows_written"], 2)
        self.assertEqual(len(self._read_export_rows()), 2)

    def test_api_export_to_connection(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            f"/api/images/blob-browse/{self.view.id}/export-to-connection/",
            {
                "target_db_alias": "default",
                "target_table": EXPORT_TABLE,
                "if_exists": "fail",
            },
            format="json",
        )
        self.assertIn(res.status_code, {200, 202}, res.data)
        self.assertEqual(res.data["code"], 0)
        job = res.data["data"]["job"]
        self.assertTrue(job.get("id"))
        # sqlite runs export synchronously in kick_export_job_async
        detail = self.client.get(f"/api/images/blob-browse/export-jobs/{job['id']}/")
        self.assertEqual(detail.status_code, 200)
        job_body = detail.data["data"]
        self.assertEqual(job_body["status"], "completed", job_body.get("message"))
        self.assertEqual(job_body["rows_written"], 2)
        result = job_body.get("result") or {}
        self.assertTrue(result.get("target_view_id"))
        self.assertTrue(result.get("target_view_created"))
        rows = self._read_export_rows()
        self.assertEqual(rows[0][2], "2026/01/a.png")
        self.assertEqual(rows[1][2], "")

    def test_export_creates_target_browse_view(self):
        from images.blob_table_view_service import fetch_simulated_table_rows
        from images.models import BlobTableView

        result = export_simulated_table_to_connection(
            self.view.id,
            target_db_alias="default",
            target_table=EXPORT_TABLE,
            if_exists="fail",
        )
        self.assertTrue(result.get("target_view_created"))
        self.assertTrue(result.get("target_view_id"))
        target = BlobTableView.objects.get(pk=result["target_view_id"])
        self.assertEqual(target.db_alias, "default")
        self.assertEqual(target.source_table, EXPORT_TABLE)
        self.assertEqual(target.blob_column, "photo")
        self.assertIn("photo", target.blob_columns)
        self.assertEqual(target.path_lookup_table, "legacy_photos")
        self.assertEqual(target.source_uid, self.view.source_uid)
        self.assertIn("路径导出", target.name)

        page = fetch_simulated_table_rows(target, offset=0, limit=10)
        row1 = next(r for r in page["rows"] if str(r.get("id")) == "1")
        self.assertEqual(row1["photo"]["status"], "migrated")
        self.assertEqual(row1["photo"]["image_info_id"], self.image.id)
        self.assertEqual(row1["photo"]["path"], "2026/01/a.png")

        again = export_simulated_table_to_connection(
            self.view.id,
            target_db_alias="default",
            target_table=EXPORT_TABLE,
            if_exists="replace",
        )
        self.assertFalse(again.get("target_view_created"))
        self.assertEqual(again.get("target_view_id"), result["target_view_id"])
        self.assertEqual(
            BlobTableView.objects.filter(db_alias="default", source_table=EXPORT_TABLE).count(),
            1,
        )
        # Source view still browsable after export.
        source_page = fetch_simulated_table_rows(self.view, offset=0, limit=10)
        self.assertEqual(len(source_page["rows"]), 2)
        self.assertEqual(source_page["rows"][0]["photo"]["status"], "migrated")

    def test_export_preview_from_stored_path_without_map_uid(self):
        """Path-export table preview works even when maps lack source_uid."""
        from images.blob_table_view_service import fetch_simulated_table_rows
        from images.models import BlobTableView, ImageSourceMap

        # Ensure map is legacy (empty uid) while view may carry a uid.
        ImageSourceMap.objects.filter(source_table="legacy_photos").update(source_uid="")
        self.view.source_uid = "11111111-1111-4111-8111-111111111111"
        self.view.save(update_fields=["source_uid"])

        result = export_simulated_table_to_connection(
            self.view.id,
            target_db_alias="default",
            target_table=EXPORT_TABLE,
            if_exists="fail",
        )
        target = BlobTableView.objects.get(pk=result["target_view_id"])
        page = fetch_simulated_table_rows(target, offset=0, limit=10)
        row1 = next(r for r in page["rows"] if str(r.get("id")) == "1")
        self.assertEqual(row1["photo"]["status"], "migrated")
        self.assertEqual(row1["photo"]["image_info_id"], self.image.id)
        row2 = next(r for r in page["rows"] if str(r.get("id")) == "2")
        self.assertEqual(row2["photo"]["status"], "no_data")

    def test_export_resume_from_offset(self):
        from images.blob_simulated_export_service import SimulatedExportPaused

        checks = {"n": 0}

        def pause_after_first_page():
            checks["n"] += 1
            # First loop-start check: continue; after first page write: pause.
            return checks["n"] > 1

        with self.assertRaises(SimulatedExportPaused) as ctx:
            export_simulated_table_to_connection(
                self.view.id,
                target_db_alias="default",
                target_table=EXPORT_TABLE,
                if_exists="fail",
                page_size=1,
                should_pause=pause_after_first_page,
            )
        self.assertEqual(ctx.exception.offset, 1)
        self.assertEqual(len(self._read_export_rows()), 1)

        result = export_simulated_table_to_connection(
            self.view.id,
            target_db_alias="default",
            target_table=EXPORT_TABLE,
            if_exists="fail",
            start_offset=ctx.exception.offset,
            skip_prepare=True,
            page_size=1,
        )
        self.assertEqual(result["rows_written"], 2)
        self.assertEqual(len(self._read_export_rows()), 2)

    def test_export_job_pause_resume_and_reclaim(self):
        from images.blob_simulated_export_job_service import (
            create_export_job,
            pause_export_job,
            reclaim_orphaned_export_jobs,
            resume_export_job,
        )
        from images.models import BlobSimulatedExportJob

        job = create_export_job(
            view_id=self.view.id,
            created_by="export_admin",
            target_db_alias="default",
            target_table=EXPORT_TABLE,
            if_exists="fail",
        )
        pause_export_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, BlobSimulatedExportJob.STATUS_PAUSED)

        resume_export_job(job.id)
        job.refresh_from_db()
        # sqlite sync: resume kicks queue and finishes immediately
        self.assertEqual(job.status, BlobSimulatedExportJob.STATUS_COMPLETED)
        self.assertEqual(job.rows_written, 2)

        job2 = create_export_job(
            view_id=self.view.id,
            created_by="export_admin",
            target_db_alias="default",
            target_table=EXPORT_TABLE + "_2",
            if_exists="fail",
        )
        BlobSimulatedExportJob.objects.filter(pk=job2.id).update(
            status=BlobSimulatedExportJob.STATUS_RUNNING,
            rows_written=1,
            last_offset=1,
        )
        count = reclaim_orphaned_export_jobs(reason="测试重启")
        self.assertEqual(count, 1)
        job2.refresh_from_db()
        self.assertEqual(job2.status, BlobSimulatedExportJob.STATUS_PENDING)
        self.assertEqual(job2.last_offset, 1)
