"""SQL execute API tests — Step 13."""
from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from logs.models import OperateLog
from users.models import SysUser
from utils.security_test_fixtures import sql_delete_from_images, sql_drop_table

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
INSERT OR IGNORE INTO image_info (
    id, image_name, image_path, image_width, image_height, file_size, file_suffix,
    upload_time, update_time, upload_user, is_delete, category_id, tags
) VALUES
(1, 'demo.jpg', 'upload/20260630/1/demo.jpg', 100, 80, 1024, 'jpg',
 '2026-06-30 12:00:00', '2026-06-30 12:00:00', 'admin', 0, 1, 'test'),
(2, 'a.jpg', 'upload/a.jpg', 1, 1, 1, 'jpg',
 '2026-06-30 12:00:00', '2026-06-30 12:00:00', 'admin', 0, 1, ''),
(3, 'b.jpg', 'upload/b.jpg', 1, 1, 1, 'jpg',
 '2026-06-30 12:00:00', '2026-06-30 12:00:00', 'admin', 0, 1, '');
"""


class SqlExecuteAPITestCase(TestCase):
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
            username="testuser",
            password=make_password("user123"),
            role="user",
            status=1,
        )

    def test_admin_execute_select(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/sql/execute/",
            {"sql": "SELECT id, image_name, image_path FROM image_info WHERE is_delete = 0"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], 0)
        self.assertIn("image_path", response.data["data"]["columns"])
        self.assertGreaterEqual(response.data["data"]["row_count"], 1)
        self.assertTrue(OperateLog.objects.filter(action_type="sql_execute").exists())

    def test_user_execute_select(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/sql/execute/",
            {"sql": "SELECT id, image_name FROM image_info WHERE is_delete = 0"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], 0)
        self.assertGreaterEqual(response.data["data"]["row_count"], 1)

    def test_rejects_drop(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/sql/execute/",
            {"sql": sql_drop_table()},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.data["code"], 0)

    def test_validate_endpoint(self):
        self.client.force_authenticate(user=self.admin)
        ok = self.client.post(
            "/api/sql/validate/",
            {"sql": "SELECT id FROM image_info WHERE id = 1"},
            format="json",
        )
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.data["data"]["valid"])

        bad = self.client.post(
            "/api/sql/validate/",
            {"sql": sql_delete_from_images()},
            format="json",
        )
        self.assertEqual(bad.status_code, 400)

    @override_settings(SQL_MAX_ROWS=2)
    def test_row_limit_truncated(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/sql/execute/",
            {"sql": "SELECT id FROM image_info ORDER BY id"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["row_count"], 2)
        self.assertTrue(response.data["data"]["truncated"])


class SqlTemplateAPITestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_TABLES)

    def setUp(self):
        self.client = APIClient()
        self.admin = SysUser.objects.create(
            username="admin_tpl",
            password=make_password("admin123"),
            role="admin",
            status=1,
        )
        self.user = SysUser.objects.create(
            username="user_tpl",
            password=make_password("user123"),
            role="user",
            status=1,
        )

    def test_list_templates_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/sql/templates/")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data["data"]), 3)

    def test_create_template_as_user(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/sql/templates/",
            {"name": "test", "sql": "SELECT 1"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["name"], "test")

    def test_create_template_as_admin(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/sql/templates/",
            {"name": "我的模板", "sql": "SELECT id FROM image_info LIMIT 5"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["name"], "我的模板")
