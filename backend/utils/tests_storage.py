"""Storage backend unit tests."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from utils.path_builder import build_relative_path
from utils.storage import LocalImageStorage, MinioImageStorage, get_image_storage, reset_image_storage_cache


class LocalImageStorageTests(SimpleTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.upload_root = Path(self.temp_dir.name)
        self.storage = LocalImageStorage(self.upload_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_write_read_delete_roundtrip(self):
        rel = build_relative_path(category_id=2, suffix="jpg")
        payload = b"fake-image-bytes"
        self.storage.write_bytes(rel, payload)
        self.assertTrue(self.storage.exists(rel))
        self.assertEqual(self.storage.read_bytes(rel), payload)
        deleted, size = self.storage.delete(rel)
        self.assertTrue(deleted)
        self.assertEqual(size, len(payload))
        self.assertFalse(self.storage.exists(rel))

    def test_stat_returns_size_and_mtime(self):
        rel = build_relative_path(category_id=1, suffix="png")
        self.storage.write_bytes(rel, b"12345")
        stat = self.storage.stat(rel)
        self.assertIsNotNone(stat)
        assert stat is not None
        self.assertEqual(stat.size, 5)


class MinioImageStorageTests(SimpleTestCase):
    @mock.patch("minio.Minio")
    def test_object_key_includes_prefix(self, minio_cls):
        minio_cls.return_value = mock.Mock()
        storage = MinioImageStorage(
            endpoint="http://192.168.9.9:9000",
            access_key="key",
            secret_key="secret",
            bucket="biox",
            prefix="data/image_db",
        )
        rel = build_relative_path(category_id=3, suffix="jpg")
        self.assertEqual(storage._object_key(rel), f"data/image_db/{rel}")


class GetImageStorageFactoryTests(SimpleTestCase):
    def tearDown(self):
        reset_image_storage_cache()

    @override_settings(STORAGE_BACKEND="local", UPLOAD_ROOT="/tmp/image_db_test_upload")
    def test_factory_returns_local_backend(self):
        reset_image_storage_cache()
        storage = get_image_storage()
        self.assertEqual(storage.backend_name, "local")

    @override_settings(
        STORAGE_BACKEND="minio",
        MINIO_ENDPOINT="http://192.168.9.9:9000",
        MINIO_ACCESS_KEY="user",
        MINIO_SECRET_KEY="pass",
        MINIO_BUCKET="biox",
        MINIO_PREFIX="data/image_db",
        MINIO_SECURE=False,
    )
    @mock.patch("minio.Minio")
    def test_factory_returns_minio_backend(self, minio_cls):
        minio_cls.return_value = mock.Mock()
        reset_image_storage_cache()
        storage = get_image_storage()
        self.assertEqual(storage.backend_name, "minio")
