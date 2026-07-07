"""Tests for SQL query service (PR3 external DB context)."""
from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from sqlquery.services import execute_select_sql, resolve_sql_connection_context
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
CREATE TABLE IF NOT EXISTS image_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_name VARCHAR(255) NOT NULL DEFAULT '',
    image_path VARCHAR(500) NOT NULL DEFAULT '',
    is_delete SMALLINT NOT NULL DEFAULT 0
);
"""


class SqlQueryServiceTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_TABLES)

    def setUp(self):
        self.client = APIClient()
        self.user = SysUser.objects.create(
            username="sql_user",
            password=make_password("pass"),
            role="admin",
            status=1,
        )

    def test_resolve_default_connection(self):
        ctx = resolve_sql_connection_context()
        self.assertEqual(ctx.db_alias, "default")

    def test_execute_select_sql_default(self):
        result = execute_select_sql("SELECT COUNT(*) AS cnt FROM image_info")
        self.assertEqual(result["columns"], ["cnt"])
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["db_alias"], "default")

    def test_api_execute_with_db_alias(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.post(
            "/api/sql/execute/",
            {"sql": "SELECT COUNT(*) AS cnt FROM image_info", "db_alias": "default"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"]["row_count"], 1)
