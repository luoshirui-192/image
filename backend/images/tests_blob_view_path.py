"""Tests for SQL VIEW path lookup helpers (PR2)."""
from __future__ import annotations

from django.test import SimpleTestCase

from images.blob_view_path_service import parse_simple_view_base_table


class BlobViewPathHelperTestCase(SimpleTestCase):
    def test_parse_simple_view_base_table(self):
        definition = "SELECT `id`, `photo` FROM `legacy_photos` WHERE `status` = 1"
        self.assertEqual(parse_simple_view_base_table(definition), "legacy_photos")

    def test_parse_simple_view_rejects_join(self):
        definition = "SELECT a.id FROM photos a JOIN thumbs b ON a.id = b.id"
        self.assertIsNone(parse_simple_view_base_table(definition))
