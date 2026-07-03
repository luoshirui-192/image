"""Tests for BLOB migration service and API."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from images.blob_migration_service import count_migration_candidates, run_blob_migration
from images.models import BlobMigrationSource, ImageInfo, ImageSourceMap
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
    name_column VARCHAR(64) NOT NULL DEFAULT '',
    suffix_column VARCHAR(64) NOT NULL DEFAULT '',
    category_id INTEGER NOT NULL,
    upload_user VARCHAR(100) NOT NULL DEFAULT 'migration',
    tags VARCHAR(500) NOT NULL DEFAULT '',
    where_clause VARCHAR(500) NOT NULL DEFAULT '',
    db_alias VARCHAR(32) NOT NULL DEFAULT 'default',
    enabled SMALLINT NOT NULL DEFAULT 1,
    last_run_at DATETIME NULL,
    create_time DATETIME NULL
);
CREATE TABLE IF NOT EXISTS image_source_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table VARCHAR(64) NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    image_info_id INTEGER NOT NULL,
    migrated_at DATETIME NOT NULL,
    UNIQUE(source_table, source_id)
);
CREATE TABLE IF NOT EXISTS legacy_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title VARCHAR(100) NOT NULL DEFAULT '',
    photo BLOB NOT NULL
);
"""


def make_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(buf, format="PNG")
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
