"""Tests for virtual BLOB table views."""
from __future__ import annotations

import io
import tempfile

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from images.blob_table_view_service import create_table_view, fetch_view_rows
from images.models import BlobTableView, ImageInfo, ImageSourceMap
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
    UNIQUE(source_table, source_id, source_column)
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
    thumb BLOB NOT NULL DEFAULT X''
);
CREATE TABLE IF NOT EXISTS external_db_connection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL DEFAULT '',
    host VARCHAR(255) NOT NULL DEFAULT '',
    port INTEGER NOT NULL DEFAULT 3306,
    db_name VARCHAR(64) NOT NULL DEFAULT '',
    username VARCHAR(100) NOT NULL DEFAULT '',
    password_encrypted TEXT NOT NULL DEFAULT '',
    charset VARCHAR(16) NOT NULL DEFAULT 'utf8',
    remark VARCHAR(500) NOT NULL DEFAULT '',
    enabled SMALLINT NOT NULL DEFAULT 1,
    last_test_at DATETIME NULL,
    last_test_ok SMALLINT NOT NULL DEFAULT 0,
    last_test_message VARCHAR(500) NOT NULL DEFAULT '',
    create_time DATETIME NULL,
    update_time DATETIME NULL
);
"""


def make_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


class BlobTableViewTestCase(TestCase):
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
            username="view_admin",
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
            png = make_png_bytes()
            cursor.execute(
                "INSERT INTO legacy_photos (id, title, photo) VALUES (1, 'a.png', ?)",
                [png],
            )
            cursor.execute(
                "INSERT INTO legacy_photos (id, title, photo) VALUES (2, 'b.png', ?)",
                [png],
            )
            cursor.execute(
                "INSERT INTO legacy_photos (id, title, photo) VALUES (3, 'empty.png', X'')",
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
            name="legacy view",
            db_alias="default",
            source_table="legacy_photos",
            source_pk_column="id",
            blob_column="photo",
        )

    def test_fetch_view_rows_substitutes_path(self):
        payload = fetch_view_rows(self.view.id, offset=0, limit=10)
        self.assertEqual(payload["total"], 3)
        self.assertFalse(payload["has_more"])
        self.assertEqual(len(payload["rows"]), 3)
        row1 = payload["rows"][0]
        self.assertEqual(row1["title"], "a.png")
        self.assertEqual(row1["photo"]["status"], "migrated")
        self.assertEqual(row1["photo"]["path"], "2026/01/a.png")
        self.assertEqual(row1["photo"]["image_info_id"], self.image.id)
        row2 = payload["rows"][1]
        self.assertEqual(row2["photo"]["status"], "pending")
        self.assertEqual(row2["photo"]["display"], "未迁移")

    def test_empty_blob_shows_no_data(self):
        payload = fetch_view_rows(self.view.id, offset=0, limit=10)
        row3 = next(row for row in payload["rows"] if str(row["id"]) == "3")
        self.assertEqual(row3["photo"]["status"], "no_data")
        self.assertEqual(row3["photo"]["display"], "无数据")

    def test_join_view_empty_lookup_blob_shows_no_data(self):
        from images.blob_schema_helpers import serialize_blob_column_path_mappings

        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS join_view_rows")
            cursor.execute("DROP TABLE IF EXISTS join_image_store")
            cursor.execute(
                """
                CREATE TABLE join_view_rows (
                    id INTEGER PRIMARY KEY,
                    src_fname VARCHAR(100) NOT NULL DEFAULT '',
                    src_image_data BLOB
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE join_image_store (
                    Fname VARCHAR(100) PRIMARY KEY,
                    image_data BLOB
                )
                """
            )
            cursor.execute(
                "INSERT INTO join_view_rows (id, src_fname) VALUES (1, 'missing.jpg')"
            )
            cursor.execute(
                "INSERT INTO join_view_rows (id, src_fname) VALUES (2, 'present.jpg')"
            )
            png = make_png_bytes()
            cursor.execute(
                "INSERT INTO join_image_store (Fname, image_data) VALUES ('present.jpg', ?)",
                [png],
            )

        mappings = serialize_blob_column_path_mappings(
            [
                {
                    "view_column": "src_image_data",
                    "lookup_table": "join_image_store",
                    "source_id_column": "src_fname",
                    "source_column": "image_data",
                    "lookup_id_column": "Fname",
                }
            ]
        )
        join_view = BlobTableView.objects.create(
            name="join view",
            db_alias="default",
            source_table="join_view_rows",
            source_object_type="view",
            path_lookup_table="join_image_store",
            blob_column_path_mappings=mappings,
            source_pk_column="id",
            blob_column="src_image_data",
            blob_columns='["src_image_data"]',
            create_time=timezone.now(),
            update_time=timezone.now(),
        )
        payload = fetch_view_rows(join_view.id, offset=0, limit=10)
        by_id = {str(row["id"]): row for row in payload["rows"]}
        self.assertEqual(by_id["1"]["src_image_data"]["status"], "no_data")
        self.assertEqual(by_id["1"]["src_image_data"]["display"], "无数据")
        self.assertEqual(by_id["2"]["src_image_data"]["status"], "pending")
        self.assertEqual(by_id["2"]["src_image_data"]["display"], "未迁移")

    def test_api_list_and_rows(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get("/api/images/blob-migration/table-views/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["data"]), 1)

        res = self.client.get(f"/api/images/blob-migration/table-views/{self.view.id}/rows/?limit=1&offset=0")
        self.assertEqual(res.status_code, 200)
        body = res.json()["data"]
        self.assertTrue(body["has_more"])
        self.assertEqual(len(body["rows"]), 1)

    def test_api_create_view(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/images/blob-migration/table-views/",
            {
                "name": "new view",
                "db_alias": "default",
                "source_table": "legacy_photos",
                "source_pk_column": "id",
                "blob_column": "photo",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(BlobTableView.objects.count(), 2)

    def test_deleted_image_shows_status(self):
        ImageInfo.objects.filter(pk=self.image.id).update(is_delete=1)
        payload = fetch_view_rows(self.view.id, offset=0, limit=1)
        photo = payload["rows"][0]["photo"]
        self.assertEqual(photo["status"], "deleted")
        self.assertEqual(photo["display"], "已删除")

    def test_multi_blob_columns_substitute_paths(self):
        now = timezone.now()
        png = make_png_bytes()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM legacy_dual_blob")
            cursor.execute(
                "INSERT INTO legacy_dual_blob (id, title, photo, thumb) VALUES (1, 'a.png', ?, ?)",
                [png, png],
            )

        photo_image = ImageInfo.objects.create(
            image_name="dual-a.png",
            image_path="2026/01/dual-a.png",
            image_width=8,
            image_height=6,
            file_size=100,
            file_suffix=".png",
            upload_time=now,
            update_time=now,
            upload_user="test",
            is_delete=0,
        )
        thumb_image = ImageInfo.objects.create(
            image_name="dual-thumb.png",
            image_path="2026/01/dual-thumb.png",
            image_width=8,
            image_height=6,
            file_size=80,
            file_suffix=".png",
            upload_time=now,
            update_time=now,
            upload_user="test",
            is_delete=0,
        )
        ImageSourceMap.objects.create(
            source_table="legacy_dual_blob",
            source_id="1",
            source_column="photo",
            image_info_id=photo_image.id,
            migrated_at=now,
        )
        ImageSourceMap.objects.create(
            source_table="legacy_dual_blob",
            source_id="1",
            source_column="thumb",
            image_info_id=thumb_image.id,
            migrated_at=now,
        )

        multi_view = create_table_view(
            name="multi blob",
            db_alias="default",
            source_table="legacy_dual_blob",
            source_pk_column="id",
            blob_column="photo",
            blob_columns=["photo", "thumb"],
        )
        payload = fetch_view_rows(multi_view.id, offset=0, limit=1)
        row = payload["rows"][0]
        self.assertEqual(row["photo"]["status"], "migrated")
        self.assertEqual(row["thumb"]["status"], "migrated")
        self.assertEqual(row["thumb"]["image_info_id"], thumb_image.id)

    def test_api_blob_browse_alias_list(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get("/api/images/blob-browse/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["data"]), 1)
