"""Logs API and maintenance tests — Step 16."""
from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from images.models import ImageInfo
from logs.models import OperateLog
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
CREATE TABLE IF NOT EXISTS image_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_name VARCHAR(255) NOT NULL DEFAULT '',
    image_path VARCHAR(500) NOT NULL DEFAULT '',
    image_width INTEGER NOT NULL DEFAULT 0,
    image_height INTEGER NOT NULL DEFAULT 0,
    file_size INTEGER NOT NULL DEFAULT 0,
    file_suffix VARCHAR(20) NOT NULL DEFAULT '',
    upload_time DATETIME NOT NULL,
    update_time DATETIME NOT NULL,
    upload_user VARCHAR(100) NOT NULL DEFAULT '',
    is_delete SMALLINT NOT NULL DEFAULT 0,
    category_id INTEGER NULL,
    tags VARCHAR(500) NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS image_category (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name VARCHAR(100) NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0,
    create_time DATETIME NULL
);
"""


class LogsAPITestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_TABLES)

    def setUp(self):
        self.client = APIClient()
        self.admin = SysUser.objects.create(
            username="admin",
            password=make_password("admin123"),
            role="admin",
            status=1,
        )
        self.user = SysUser.objects.create(
            username="viewer",
            password=make_password("pass123"),
            role="user",
            status=1,
        )
        OperateLog.objects.create(
            username="admin",
            action_type="login",
            detail="login success",
            ip="127.0.0.1",
            create_time=timezone.now(),
        )

    def test_logs_list_admin_only(self):
        self.client.force_authenticate(user=self.admin)
        ok = self.client.get("/api/logs/")
        self.assertEqual(ok.status_code, 200)
        self.assertGreaterEqual(ok.data["data"]["count"], 1)

        self.client.force_authenticate(user=self.user)
        denied = self.client.get("/api/logs/")
        self.assertEqual(denied.status_code, 403)

    def test_logs_filter_by_action_type(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/logs/", {"action_type": "login"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["count"], 1)

    def test_storage_stats(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/logs/stats/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("image_active_count", response.data["data"])


class MaintenanceCommandTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.upload_root = Path(cls._temp_dir.name) / "upload"
        cls.thumb_root = Path(cls._temp_dir.name) / "thumb_cache"
        cls.upload_root.mkdir(parents=True)
        cls.thumb_root.mkdir(parents=True)

        rel = "upload/20260630/1/550e8400-e29b-41d4-a716-446655440000.jpg"
        cls.rel_path = rel
        file_path = cls.upload_root / "20260630" / "1" / "550e8400-e29b-41d4-a716-446655440000.jpg"
        file_path.parent.mkdir(parents=True)
        file_path.write_bytes(b"fake-image-data")

        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_TABLES)

    @classmethod
    def tearDownClass(cls):
        cls._temp_dir.cleanup()
        super().tearDownClass()

    def test_cleanup_deleted_images_command(self):
        old_time = timezone.now() - timedelta(days=1)
        ImageInfo.objects.create(
            image_name="old.jpg",
            image_path=self.rel_path,
            image_width=1,
            image_height=1,
            file_size=100,
            file_suffix="jpg",
            upload_time=old_time,
            update_time=old_time,
            upload_user="admin",
            is_delete=1,
            category_id=1,
            tags="",
        )

        with override_settings(
            UPLOAD_ROOT=str(self.upload_root),
            THUMB_CACHE_ROOT=str(self.thumb_root),
            DELETED_IMAGE_RETENTION_DAYS=0,
        ):
            call_command("cleanup_deleted_images", "--days=0")
            self.assertFalse(
                (self.upload_root / "20260630" / "1" / "550e8400-e29b-41d4-a716-446655440000.jpg").is_file()
            )

    def test_purge_old_logs_command(self):
        OperateLog.objects.create(
            username="admin",
            action_type="upload",
            detail="old",
            ip="127.0.0.1",
            create_time=timezone.now() - timedelta(days=100),
        )
        self.assertGreater(OperateLog.objects.count(), 0)
        with override_settings(LOG_RETENTION_DAYS=0):
            call_command("purge_old_logs", "--days=0")
        self.assertEqual(OperateLog.objects.count(), 0)
