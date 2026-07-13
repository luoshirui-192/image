"""Tests for default category resolution."""
from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from images.category_service import DEFAULT_CATEGORY_NAMES, ensure_default_category, resolve_category_id
from images.models import ImageCategory

SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS image_category (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name VARCHAR(100) NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0,
    create_time DATETIME NULL
);
"""


class DefaultCategoryServiceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.executescript(SQLITE_TABLES)

    def test_ensure_default_creates_when_empty(self):
        self.assertEqual(ImageCategory.objects.count(), 0)
        category = ensure_default_category()
        self.assertEqual(category.category_name, DEFAULT_CATEGORY_NAMES[0])
        self.assertEqual(ImageCategory.objects.count(), 1)

    def test_ensure_default_prefers_legacy_seed_name(self):
        legacy = ImageCategory.objects.create(
            category_name="默认分类",
            sort=0,
            create_time=timezone.now(),
        )
        ImageCategory.objects.create(
            category_name="其他",
            sort=1,
            create_time=timezone.now(),
        )
        self.assertEqual(ensure_default_category().id, legacy.id)

    def test_resolve_category_id_uses_default_when_omitted(self):
        default = ImageCategory.objects.create(
            category_name="默认",
            sort=0,
            create_time=timezone.now(),
        )
        self.assertEqual(resolve_category_id(None), default.id)
        self.assertEqual(resolve_category_id(""), default.id)

    def test_resolve_category_id_keeps_explicit_valid_id(self):
        default = ImageCategory.objects.create(category_name="默认", sort=0, create_time=timezone.now())
        other = ImageCategory.objects.create(category_name="风景", sort=1, create_time=timezone.now())
        self.assertEqual(resolve_category_id(default.id), default.id)
        self.assertEqual(resolve_category_id(other.id), other.id)
