"""Tests for blob catalog API (PR1 / PR4)."""
from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from images.blob_catalog_service import (
    BlobCatalogError,
    list_catalog_connections,
    list_connection_databases,
)
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


class BlobCatalogTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_TABLES)

    def setUp(self):
        self.client = APIClient()
        self.user = SysUser.objects.create(
            username="catalog_user",
            password=make_password("pass"),
            role="admin",
            status=1,
        )
        self.client.force_authenticate(user=self.user)

    def test_list_catalog_connections_includes_default(self):
        items = list_catalog_connections()
        aliases = {item.get("alias") for item in items}
        self.assertIn("default", aliases)

    def test_list_connection_databases_default_sqlite(self):
        databases = list_connection_databases(db_alias="default")
        self.assertEqual(len(databases), 1)
        self.assertIn("name", databases[0])

    def test_api_connections(self):
        res = self.client.get("/api/images/blob-catalog/connections/")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["code"], 0)
        self.assertIsInstance(body["data"], list)

    def test_api_databases_requires_context(self):
        res = self.client.get("/api/images/blob-catalog/databases/")
        self.assertEqual(res.status_code, 400)

    def test_api_databases_with_db_alias(self):
        res = self.client.get("/api/images/blob-catalog/databases/?db_alias=default")
        self.assertEqual(res.status_code, 200)
        databases = res.json()["data"]["databases"]
        self.assertGreaterEqual(len(databases), 1)

    def test_api_objects_requires_database(self):
        res = self.client.get("/api/images/blob-catalog/objects/?db_alias=default")
        self.assertEqual(res.status_code, 400)

    def test_api_objects_non_mysql_vendor(self):
        res = self.client.get(
            "/api/images/blob-catalog/objects/?db_alias=default&database=main"
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("暂不支持", res.json()["message"])

    def test_api_object_detail_non_mysql_vendor(self):
        res = self.client.get(
            "/api/images/blob-catalog/objects/legacy_photos/?db_alias=default&database=main"
        )
        self.assertEqual(res.status_code, 400)

    def test_service_objects_error_message(self):
        with self.assertRaises(BlobCatalogError) as ctx:
            from images.blob_catalog_service import list_database_objects

            list_database_objects("main", db_alias="default")
        self.assertIn("暂不支持", str(ctx.exception))
