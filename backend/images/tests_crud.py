"""Image CRUD API tests — Step 15."""
from __future__ import annotations

import tempfile
from pathlib import Path

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from images.models import ImageCategory, ImageInfo
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
"""


class ImageCrudAPITestCase(TestCase):
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

    def _settings(self):
        return override_settings(UPLOAD_ROOT=str(self.upload_root))

    def _write_image_file(self, relative_path: str, content: bytes = b"fake-image") -> None:
        target = self.upload_root.parent.joinpath(*relative_path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def setUp(self):
        self.client = APIClient()
        self.user = SysUser.objects.create(
            username="viewer",
            password=make_password("pass123"),
            role="user",
            status=1,
        )
        self.admin = SysUser.objects.create(
            username="admin",
            password=make_password("admin123"),
            role="admin",
            status=1,
        )
        self.category = ImageCategory.objects.create(category_name="风景", sort=1)
        now = timezone.now()
        self.image = ImageInfo.objects.create(
            image_name="lake.jpg",
            image_path="upload/20260630/1/550e8400-e29b-41d4-a716-446655440000.jpg",
            image_width=800,
            image_height=600,
            file_size=2048,
            file_suffix="jpg",
            upload_time=now,
            update_time=now,
            upload_user="viewer",
            is_delete=0,
            category_id=self.category.id,
            tags="风景,湖",
        )

    def test_list_requires_auth(self):
        response = self.client.get("/api/images/")
        self.assertEqual(response.status_code, 401)

    def test_list_and_filter(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/images/", {"keyword": "lake", "category_id": self.category.id})
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["image_name"], "lake.jpg")

    def test_get_detail(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/images/{self.image.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["tags"], "风景,湖")

    def test_patch_update_tags(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            f"/api/images/{self.image.id}/",
            {"tags": "更新标签", "image_name": "new-name.jpg"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.image.refresh_from_db()
        self.assertEqual(self.image.tags, "更新标签")
        self.assertEqual(self.image.image_name, "new-name.jpg")
        self.assertTrue(OperateLog.objects.filter(action_type="image_update").exists())

    def test_logical_delete(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f"/api/images/{self.image.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("deletion_info", response.data["data"])
        self.assertIn("notice", response.data["data"])

        self.image.refresh_from_db()
        self.assertEqual(self.image.is_delete, 1)

        detail = self.client.get(f"/api/images/{self.image.id}/")
        self.assertEqual(detail.status_code, 404)

        listed = self.client.get("/api/images/")
        self.assertEqual(listed.data["data"]["count"], 0)

    def test_restore_deleted_image(self):
        self._write_image_file(self.image.image_path)
        with self._settings():
            self.client.force_authenticate(user=self.user)
            self.client.delete(f"/api/images/{self.image.id}/")

            restore = self.client.post(f"/api/images/{self.image.id}/restore/")
            self.assertEqual(restore.status_code, 200)

        self.image.refresh_from_db()
        self.assertEqual(self.image.is_delete, 0)

        self.client.force_authenticate(user=self.user)
        listed = self.client.get("/api/images/")
        self.assertEqual(listed.data["data"]["count"], 1)

    def test_deletion_policy(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/images/deletion-policy/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.data["data"]["retention_days"], 1)

    def test_user_include_own_deleted(self):
        self.image.is_delete = 1
        self.image.save(update_fields=["is_delete"])

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/images/", {"include_deleted": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["count"], 1)
        self.assertIsNotNone(response.data["data"]["results"][0]["deletion_info"])

    def test_admin_include_deleted(self):
        self.image.is_delete = 1
        self.image.save(update_fields=["is_delete"])

        self.client.force_authenticate(user=self.admin)
        response = self.client.get("/api/images/", {"include_deleted": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["count"], 1)

    def test_user_cannot_see_others_deleted(self):
        self.image.is_delete = 0
        self.image.save(update_fields=["is_delete"])
        ImageInfo.objects.create(
            image_name="other.jpg",
            image_path="upload/20260630/1/other.jpg",
            image_width=100,
            image_height=100,
            file_size=100,
            file_suffix="jpg",
            upload_time=self.image.upload_time,
            update_time=self.image.update_time,
            upload_user="admin",
            is_delete=1,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/images/", {"include_deleted": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["count"], 1)
        self.assertEqual(response.data["data"]["results"][0]["image_name"], "lake.jpg")
        self.assertEqual(response.data["data"]["results"][0]["is_delete"], 0)

    def test_user_cannot_restore_others_deleted(self):
        self._write_image_file("upload/20260630/1/other.jpg")
        other = ImageInfo.objects.create(
            image_name="other.jpg",
            image_path="upload/20260630/1/other.jpg",
            image_width=100,
            image_height=100,
            file_size=100,
            file_suffix="jpg",
            upload_time=self.image.upload_time,
            update_time=self.image.update_time,
            upload_user="admin",
            is_delete=1,
        )
        with self._settings():
            self.client.force_authenticate(user=self.user)
            response = self.client.post(f"/api/images/{other.id}/restore/")
        self.assertEqual(response.status_code, 400)

    def test_batch_delete(self):
        now = self.image.upload_time
        second = ImageInfo.objects.create(
            image_name="batch2.jpg",
            image_path="upload/20260630/1/batch2.jpg",
            image_width=100,
            image_height=100,
            file_size=100,
            file_suffix="jpg",
            upload_time=now,
            update_time=now,
            upload_user="viewer",
            is_delete=0,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/images/batch-delete/",
            {"ids": [self.image.id, second.id, 99999]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assertEqual(data["summary"]["succeeded"], 2)
        self.assertEqual(data["summary"]["failed"], 1)

        self.image.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.image.is_delete, 1)
        self.assertEqual(second.is_delete, 1)

        listed = self.client.get("/api/images/")
        self.assertEqual(listed.data["data"]["count"], 0)
        self.assertTrue(OperateLog.objects.filter(action_type="image_batch_delete").exists())

    def test_invalid_category_on_patch(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            f"/api/images/{self.image.id}/",
            {"category_id": 9999},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_client_list_hides_image_path(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/images/")
        self.assertEqual(response.status_code, 200)
        item = response.data["data"]["results"][0]
        self.assertNotIn("image_path", item)

    def test_client_cannot_delete_others_image(self):
        other = ImageInfo.objects.create(
            image_name="other.jpg",
            image_path="upload/20260630/1/other.jpg",
            image_width=100,
            image_height=100,
            file_size=100,
            file_suffix="jpg",
            upload_time=self.image.upload_time,
            update_time=self.image.update_time,
            upload_user="admin",
            is_delete=0,
            category_id=self.category.id,
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f"/api/images/{other.id}/")
        self.assertEqual(response.status_code, 403)
        other.refresh_from_db()
        self.assertEqual(other.is_delete, 0)

    def test_client_cannot_patch_others_image(self):
        other = ImageInfo.objects.create(
            image_name="other2.jpg",
            image_path="upload/20260630/1/other2.jpg",
            image_width=100,
            image_height=100,
            file_size=100,
            file_suffix="jpg",
            upload_time=self.image.upload_time,
            update_time=self.image.update_time,
            upload_user="admin",
            is_delete=0,
            category_id=self.category.id,
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            f"/api/images/{other.id}/",
            {"tags": "hack"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
