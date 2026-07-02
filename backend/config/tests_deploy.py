"""步骤 28~29 — 部署配置渲染测试。"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RENDER_NGINX = PROJECT_ROOT / "scripts" / "render_nginx_config.py"
RENDER_GUNICORN = PROJECT_ROOT / "scripts" / "render_gunicorn_service.py"
GUNICORN_CONF = PROJECT_ROOT / "deploy/gunicorn/gunicorn.conf.py"
BACKUP_MYSQL = PROJECT_ROOT / "scripts" / "backup_mysql.py"
SMOKE_TEST = PROJECT_ROOT / "scripts" / "smoke_test.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class RenderNginxConfigTests(unittest.TestCase):
    def test_render_default_upload_disabled(self):
        mod = _load_module(RENDER_NGINX, "render_nginx_config")
        text = mod.render(PROJECT_ROOT / "deploy/paths.env.example")
        self.assertIn("upstream image_db_backend", text)
        self.assertIn("location /api/", text)
        self.assertIn("try_files $uri $uri/ /index.html", text)
        self.assertNotIn("location /upload/", text)

    def test_render_upload_enabled(self):
        mod = _load_module(RENDER_NGINX, "render_nginx_config")
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as f:
            f.write("PROJECT_ROOT=/srv/app\n")
            f.write("SERVER_NAME=test.local\n")
            f.write("ENABLE_UPLOAD_DIRECT=1\n")
            path = Path(f.name)
        try:
            text = mod.render(path)
            self.assertIn("location /upload/", text)
            self.assertIn("alias /srv/app/upload/", text)
        finally:
            path.unlink(missing_ok=True)


class GunicornDeployTests(unittest.TestCase):
    def test_gunicorn_conf_paths(self):
        mod = _load_module(GUNICORN_CONF, "gunicorn_conf")
        self.assertEqual(mod.PROJECT_ROOT, PROJECT_ROOT)
        self.assertEqual(mod.BACKEND_DIR, PROJECT_ROOT / "backend")
        self.assertEqual(mod.wsgi_app, "config.wsgi:application")
        self.assertEqual(mod.chdir, str(PROJECT_ROOT / "backend"))

    def test_render_systemd_service(self):
        mod = _load_module(RENDER_GUNICORN, "render_gunicorn_service")
        text = mod.render(PROJECT_ROOT / "deploy/paths.env.example")
        self.assertIn("[Service]", text)
        self.assertIn("gunicorn -c", text)
        self.assertIn("config.wsgi:application", text)
        self.assertIn("GUNICORN_BIND=127.0.0.1:8000", text)
        self.assertIn("/opt/image_db/.venv/bin/gunicorn", text)


class BackupSmokeTests(unittest.TestCase):
    def test_get_db_config_mysql(self):
        mod = _load_module(BACKUP_MYSQL, "backup_mysql")
        cfg = mod.get_db_config(
            {
                "DB_ENGINE": "mysql",
                "DB_HOST": "10.0.0.1",
                "DB_PORT": "3306",
                "DB_USER": "u",
                "DB_PASSWORD": "p",
                "DB_NAME": "image_db",
            }
        )
        self.assertEqual(cfg["host"], "10.0.0.1")
        self.assertEqual(cfg["name"], "image_db")

    def test_get_db_config_rejects_sqlite(self):
        mod = _load_module(BACKUP_MYSQL, "backup_mysql")
        with self.assertRaises(RuntimeError):
            mod.get_db_config({"DB_ENGINE": "sqlite"})

    def test_build_mysqldump_cmd(self):
        mod = _load_module(BACKUP_MYSQL, "backup_mysql")
        cmd = mod.build_mysqldump_cmd(
            {"host": "h", "port": "3306", "user": "u", "name": "image_db"},
            "/usr/bin/mysqldump",
        )
        self.assertIn("--single-transaction", cmd)
        self.assertEqual(cmd[-1], "image_db")

    def test_smoke_join_url(self):
        mod = _load_module(SMOKE_TEST, "smoke_test")
        url = mod._join_url("http://127.0.0.1:8000", "/api/health/")
        self.assertEqual(url, "http://127.0.0.1:8000/api/health/")


if __name__ == "__main__":
    unittest.main()
