"""Production readiness checks."""
from __future__ import annotations

from django.test import TestCase, override_settings

from config.readiness import check_upload_writable, collect_readiness


class ReadinessTestCase(TestCase):
    def test_collect_readiness_structure(self):
        data = collect_readiness()
        self.assertIn("database", data)
        self.assertIn("upload_writable", data)
        self.assertIn("ready", data)

    @override_settings(UPLOAD_ROOT="/tmp/image_db_test_upload")
    def test_upload_writable(self):
        ok, _ = check_upload_writable()
        self.assertTrue(ok)
