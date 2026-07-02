"""Auth API tests — Step 11."""
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
"""


class AuthAPITestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_TABLES)

    def setUp(self):
        self.client = APIClient()
        SysUser.objects.create(
            username="admin_test",
            password=make_password("admin123"),
            role="admin",
            status=1,
        )
        SysUser.objects.create(
            username="user_test",
            password=make_password("user123"),
            role="user",
            status=1,
        )
        SysUser.objects.create(
            username="disabled_user",
            password=make_password("pass123"),
            role="user",
            status=0,
        )

    def test_login_success(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "admin_test", "password": "admin123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertIn("access", body["data"])
        self.assertIn("refresh", body["data"])
        self.assertEqual(body["data"]["user"]["username"], "admin_test")
        self.assertTrue(body["data"]["user"]["is_admin"])

    def test_login_wrong_password(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "admin_test", "password": "wrong"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 4001)

    def test_login_disabled_account(self):
        response = self.client.post(
            "/api/auth/login/",
            {"username": "disabled_user", "password": "pass123"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("禁用", response.json()["message"])

    def test_me_requires_auth(self):
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)

    def test_me_with_token(self):
        login = self.client.post(
            "/api/auth/login/",
            {"username": "user_test", "password": "user123"},
            format="json",
        )
        token = login.json()["data"]["access"]
        response = self.client.get("/api/auth/me/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["username"], "user_test")
        self.assertFalse(response.json()["data"]["is_admin"])

    def test_refresh_token(self):
        login = self.client.post(
            "/api/auth/login/",
            {"username": "user_test", "password": "user123"},
            format="json",
        )
        refresh = login.json()["data"]["refresh"]
        response = self.client.post("/api/auth/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json()["data"])
