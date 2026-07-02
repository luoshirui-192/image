"""System config API tests — Step 22."""
from __future__ import annotations

from unittest import mock

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import TestCase
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
"""


class SystemConfigAPITestCase(TestCase):
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

    def test_get_config_requires_admin(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/config/")
        self.assertEqual(response.status_code, 403)

    def test_get_config_as_admin(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get("/api/config/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("editable", response.data["data"])
        self.assertIn("MAX_UPLOAD_SIZE_MB", response.data["data"]["editable"])

    @mock.patch("config.system_config._write_env_file")
    def test_patch_config_updates_runtime(self, write_env_mock):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            "/api/config/",
            {"MAX_UPLOAD_SIZE_MB": 30, "THUMB_SIZE": 240},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["editable"]["MAX_UPLOAD_SIZE_MB"]["value"], 30)
        self.assertEqual(response.data["data"]["editable"]["THUMB_SIZE"]["value"], 240)
        write_env_mock.assert_called_once()

    def test_patch_rejects_invalid_key(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch("/api/config/", {"SECRET_KEY": "hack"}, format="json")
        self.assertEqual(response.status_code, 400)
