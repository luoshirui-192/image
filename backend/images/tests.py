"""Image upload/import API tests — Step 12."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

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


def make_test_png(name: str = "test.png", *, size: tuple[int, int] = (10, 8), color=(255, 0, 0)) -> tuple[str, io.BytesIO]:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    buf.seek(0)
    buf.name = name
    return name, buf


def make_test_bmp(name: str = "test.bmp") -> tuple[str, io.BytesIO]:
    buf = io.BytesIO()
    Image.new("RGB", (12, 10), color=(0, 128, 255)).save(buf, format="BMP")
    buf.seek(0)
    buf.name = name
    return name, buf


class ImageUploadAPITestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls.upload_root = Path(cls._temp_dir.name) / "upload"
        cls.upload_root.mkdir(parents=True)
        cls.import_root = Path(cls._temp_dir.name)
        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_TABLES)

    @classmethod
    def tearDownClass(cls):
        cls._temp_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient()
        self.user = SysUser.objects.create(
            username="uploader",
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
        from images.models import ImageCategory

        self.category = ImageCategory.objects.create(category_name="测试分类", sort=0)

    def _auth(self, user):
        self.client.force_authenticate(user=user)

    def _settings(self):
        return override_settings(
            UPLOAD_ROOT=str(self.upload_root),
            IMPORT_SCAN_ROOT=str(self.import_root),
            MAX_UPLOAD_SIZE_BYTES=20 * 1024 * 1024,
        )

    def test_upload_single_success(self):
        with self._settings():
            self._auth(self.user)
            _, png = make_test_png()
            response = self.client.post(
                "/api/images/upload/",
                {"file": png, "category_id": self.category.id, "tags": "demo"},
                format="multipart",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["summary"]["succeeded"], 1)
        image = response.data["data"]["items"][0]["image"]
        self.assertEqual(image["image_width"], 10)
        self.assertEqual(image["tags"], "demo")
        from images.models import ImageInfo

        record = ImageInfo.objects.get(pk=image["id"])
        self.assertTrue(record.image_path.startswith("upload/"))

    def test_upload_sets_local_upload_time(self):
        from django.utils import timezone
        from images.models import ImageInfo
        from utils.db_time import fetch_db_now
        from utils.path_builder import parse_relative_path

        with self._settings():
            self._auth(self.user)
            before = fetch_db_now()
            _, png = make_test_png("time_test.png")
            response = self.client.post(
                "/api/images/upload/",
                {"file": png, "category_id": self.category.id},
                format="multipart",
            )
        self.assertEqual(response.status_code, 200)
        image_id = response.data["data"]["items"][0]["image"]["id"]
        record = ImageInfo.objects.get(pk=image_id)
        self.assertIsNotNone(record.upload_time)
        self.assertEqual(record.upload_time, record.update_time)

        parsed = parse_relative_path(record.image_path)
        local_day = timezone.localtime(record.upload_time).strftime("%Y%m%d")
        self.assertEqual(parsed.date_str, local_day)

        delta = (record.upload_time - before).total_seconds()
        self.assertGreaterEqual(delta, 0)
        self.assertLess(delta, 120)

    def test_upload_bmp_success(self):
        with self._settings():
            self._auth(self.user)
            _, bmp = make_test_bmp()
            response = self.client.post(
                "/api/images/upload/",
                {"file": bmp, "category_id": self.category.id},
                format="multipart",
            )
        self.assertEqual(response.status_code, 200)
        image = response.data["data"]["items"][0]["image"]
        self.assertEqual(image["file_suffix"], "bmp")
        from images.models import ImageInfo

        record = ImageInfo.objects.get(pk=image["id"])
        self.assertTrue(record.image_path.endswith(".bmp"))

    def test_upload_rejects_non_image(self):
        with self._settings():
            self._auth(self.user)
            bad = io.BytesIO(b"not an image")
            bad.name = "bad.jpg"
            response = self.client.post("/api/images/upload/", {"file": bad}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_upload_requires_auth(self):
        _, png = make_test_png()
        response = self.client.post("/api/images/upload/", {"file": png}, format="multipart")
        self.assertEqual(response.status_code, 401)

    def test_category_list_and_create(self):
        with self._settings():
            self._auth(self.user)
            response = self.client.get("/api/images/categories/")
            self.assertEqual(response.status_code, 200)
            self.assertGreaterEqual(len(response.data["data"]), 1)

            self._auth(self.user)
            create_resp = self.client.post(
                "/api/images/categories/",
                {"category_name": "用户新建", "sort": 3},
                format="json",
            )
            self.assertEqual(create_resp.status_code, 201)

    def test_upload_requires_category(self):
        with self._settings():
            self._auth(self.user)
            _, png = make_test_png("no_cat.png")
            response = self.client.post("/api/images/upload/", {"file": png}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("分类", response.data["message"])

    def test_batch_import_from_directory(self):
        staging = self.import_root / "staging"
        staging.mkdir()
        _, png = make_test_png("import1.png")
        (staging / "import1.png").write_bytes(png.read())

        with self._settings():
            self._auth(self.admin)
            response = self.client.post(
                "/api/images/import/",
                {"directory": str(staging), "category_id": self.category.id, "recursive": False},
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["summary"]["succeeded"], 1)

    def test_import_requires_admin(self):
        with self._settings():
            self._auth(self.user)
            response = self.client.post(
                "/api/images/import/",
                {"directory": str(self.import_root)},
                format="json",
            )
        self.assertEqual(response.status_code, 403)

    def test_upload_duplicate_prompts_without_overwrite(self):
        with self._settings():
            self._auth(self.user)
            _, png = make_test_png("dup.png")
            first = self.client.post(
                "/api/images/upload/",
                {"file": png, "category_id": self.category.id},
                format="multipart",
            )
            self.assertEqual(first.status_code, 200)

            _, png2 = make_test_png("dup.png")
            second = self.client.post(
                "/api/images/upload/",
                {"file": png2, "category_id": self.category.id},
                format="multipart",
            )

        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.data["code"], 4006)
        self.assertEqual(len(second.data["data"]["duplicates"]), 1)
        self.assertEqual(second.data["data"]["duplicates"][0]["filename"], "dup.png")

    def test_upload_duplicate_overwrite(self):
        from images.models import ImageInfo

        with self._settings():
            self._auth(self.user)
            _, png = make_test_png("overwrite.png")
            first = self.client.post(
                "/api/images/upload/",
                {"file": png, "category_id": self.category.id, "tags": "old"},
                format="multipart",
            )
            first_id = first.data["data"]["items"][0]["image"]["id"]

            _, png2 = make_test_png("overwrite.png")
            second = self.client.post(
                "/api/images/upload/",
                {"file": png2, "category_id": self.category.id, "tags": "new", "overwrite": "true"},
                format="multipart",
            )

        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data["data"]["items"][0]["overwritten"])
        record = ImageInfo.objects.get(pk=first_id)
        self.assertEqual(record.tags, "new")
        self.assertEqual(ImageInfo.objects.filter(is_delete=0, image_name="overwrite.png").count(), 1)

    def test_upload_batch_intra_batch_duplicate(self):
        with self._settings():
            self._auth(self.user)
            _, png1 = make_test_png("batch-a.png")
            _, png2 = make_test_png("batch-a.png")
            response = self.client.post(
                "/api/images/upload/",
                {"files": [png1, png2], "category_id": self.category.id},
                format="multipart",
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], 4006)
        self.assertEqual(len(response.data["data"]["duplicates"]), 1)

    def test_upload_multiple_files_success(self):
        with self._settings():
            self._auth(self.user)
            _, png1 = make_test_png("multi1.png", size=(10, 8))
            _, png2 = make_test_png("multi2.png", size=(12, 10))
            response = self.client.post(
                "/api/images/upload/",
                {"files": [png1, png2], "category_id": self.category.id},
                format="multipart",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["summary"]["succeeded"], 2)
