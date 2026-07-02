"""Image file serve API tests — Step 14."""
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

from images.models import ImageInfo
from users.models import SysUser
from utils.file_security import create_image_access_token

SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS sys_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    password VARCHAR(128) NOT NULL,
    username VARCHAR(100) NOT NULL UNIQUE,
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    status SMALLINT NOT NULL DEFAULT 1,
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
"""


class ImageServeAPITestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.upload_root = Path(cls._temp_dir.name) / "upload"
        cls.thumb_root = Path(cls._temp_dir.name) / "thumb_cache"
        cls.upload_root.mkdir(parents=True)
        cls.thumb_root.mkdir(parents=True)

        cls.relative_path = "upload/20260630/1/550e8400-e29b-41d4-a716-446655440000.jpg"
        cls.abs_path = cls.upload_root / "20260630" / "1"
        cls.abs_path.mkdir(parents=True)
        cls.file_path = cls.abs_path / "550e8400-e29b-41d4-a716-446655440000.jpg"
        Image.new("RGB", (120, 80), color=(0, 128, 255)).save(cls.file_path, format="JPEG")

        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_TABLES)

    @classmethod
    def tearDownClass(cls):
        cls._temp_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient()
        self.user = SysUser.objects.create(
            username="viewer",
            password=make_password("pass123"),
            role="user",
            status=1,
        )
        now = timezone.now()
        self.image = ImageInfo.objects.create(
            image_name="serve-test.jpg",
            image_path=self.relative_path,
            image_width=120,
            image_height=80,
            file_size=self.file_path.stat().st_size,
            file_suffix="jpg",
            upload_time=now,
            update_time=now,
            upload_user="viewer",
            is_delete=0,
            category_id=1,
            tags="",
        )

    def tearDown(self):
        import gc
        gc.collect()

    def _settings(self):
        return override_settings(
            UPLOAD_ROOT=str(self.upload_root),
            THUMB_CACHE_ROOT=str(self.thumb_root),
            IMAGE_ACCESS_SECRET="test-image-secret",
            IMAGE_ACCESS_TOKEN_TTL=3600,
        )

    def test_file_requires_auth_or_token(self):
        with self._settings():
            denied = self.client.get("/api/images/file/", {"path": self.relative_path})
        self.assertEqual(denied.status_code, 403)

    def test_file_with_auth(self):
        with self._settings():
            self.client.force_authenticate(user=self.user)
            response = self.client.get("/api/images/file/", {"path": self.relative_path})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("image/"))

    def test_file_with_access_token(self):
        token = create_image_access_token(
            self.relative_path,
            "test-image-secret",
            ttl_seconds=3600,
        )
        with self._settings():
            response = self.client.get(
                "/api/images/file/",
                {"path": self.relative_path, "token": token},
            )
        self.assertEqual(response.status_code, 200)

    def test_file_by_id(self):
        with self._settings():
            self.client.force_authenticate(user=self.user)
            response = self.client.get("/api/images/file/", {"id": self.image.id})
        self.assertEqual(response.status_code, 200)

    def test_thumb_generates_cache(self):
        with self._settings():
            self.client.force_authenticate(user=self.user)
            response = self.client.get("/api/images/thumb/", {"path": self.relative_path})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        cache_files = list(self.thumb_root.glob("*.jpg"))
        self.assertEqual(len(cache_files), 1)

    def test_download_attachment(self):
        with self._settings():
            self.client.force_authenticate(user=self.user)
            response = self.client.get("/api/images/download/", {"id": self.image.id})
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])

    def test_rejects_unsafe_path(self):
        with self._settings():
            self.client.force_authenticate(user=self.user)
            response = self.client.get("/api/images/file/", {"path": "../../etc/passwd"})
        self.assertEqual(response.status_code, 403)

    def test_access_token_endpoint(self):
        with self._settings():
            self.client.force_authenticate(user=self.user)
            response = self.client.get("/api/images/access-token/", {"path": self.relative_path})
        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.data["data"])

    def test_missing_file_returns_404(self):
        with self._settings():
            self.client.force_authenticate(user=self.user)
            missing = "upload/20260630/1/00000000-0000-0000-0000-000000000099.jpg"
            response = self.client.get("/api/images/file/", {"path": missing})
        self.assertEqual(response.status_code, 404)
