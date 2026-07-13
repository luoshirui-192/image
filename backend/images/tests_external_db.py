"""Tests for Web-configured external DB connections."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from images.external_db_service import external_alias, validate_db_alias_reference
from images.models import ExternalDbConnection
from users.models import SysUser

SQLITE_EXTRA = """
CREATE TABLE IF NOT EXISTS sys_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    password VARCHAR(128) NOT NULL,
    username VARCHAR(100) NOT NULL UNIQUE,
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    status SMALLINT NOT NULL DEFAULT 1,
    create_time DATETIME NULL
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


class ExternalDbConnectionApiTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_EXTRA)

    def setUp(self):
        self.client = APIClient()
        self.admin = SysUser.objects.create(
            username="extdb_admin",
            password=make_password("admin123"),
            role="admin",
            status=1,
        )
        ExternalDbConnection.objects.all().delete()

    def test_create_and_list_connection(self):
        self.client.force_authenticate(user=self.admin)
        with patch(
            "images.external_db_views.auto_provision_table_views_for_connection",
            return_value={"created": 0, "skipped": 0, "failed": 0, "errors": []},
        ):
            res = self.client.post(
                "/api/images/blob-migration/connections/",
                {
                    "name": "旧库A",
                    "host": "192.168.1.10",
                    "port": 3306,
                    "db_name": "legacy",
                    "username": "reader",
                    "password": "secret",
                },
                format="json",
            )
        self.assertEqual(res.status_code, 201)
        record = ExternalDbConnection.objects.get()
        self.assertEqual(record.name, "旧库A")
        self.assertTrue(record.password_encrypted)
        self.assertNotIn("secret", record.password_encrypted)

        alias = external_alias(record.id)
        self.assertEqual(validate_db_alias_reference(alias), alias)

        res = self.client.get("/api/images/blob-migration/databases/")
        self.assertEqual(res.status_code, 200)
        aliases = [item["alias"] for item in res.json()["data"]]
        self.assertIn(alias, aliases)

    def test_create_requires_password(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            "/api/images/blob-migration/connections/",
            {
                "name": "旧库B",
                "host": "127.0.0.1",
                "port": 3306,
                "db_name": "legacy",
                "username": "reader",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_provision_table_views_for_saved_connection(self):
        self.client.force_authenticate(user=self.admin)
        record = ExternalDbConnection.objects.create(
            name="旧库C",
            host="192.168.1.10",
            port=3306,
            db_name="legacy",
            username="reader",
            password_encrypted="enc",
            enabled=1,
        )
        provision = {"created": 3, "skipped": 1, "failed": 0, "errors": []}
        with patch(
            "images.external_db_views.auto_provision_table_views_for_connection",
            return_value=provision,
        ) as mock_provision:
            res = self.client.post(
                f"/api/images/blob-migration/connections/{record.id}/provision-table-views/"
            )

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["code"], 0)
        self.assertIn("新增 3 个", body["message"])
        self.assertEqual(body["data"]["table_view_provision"], provision)
        mock_provision.assert_called_once()
