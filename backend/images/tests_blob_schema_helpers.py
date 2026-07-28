"""Tests for BLOB schema helper utilities."""
from __future__ import annotations

from django.test import SimpleTestCase

from images.blob_schema_helpers import (
    OBJECT_TYPE_TABLE,
    OBJECT_TYPE_VIEW,
    normalize_object_type,
    parse_blob_columns,
    primary_blob_column,
    serialize_blob_columns,
)


class BlobSchemaHelpersTest(SimpleTestCase):
    def test_parse_blob_columns_prefers_json(self):
        cols = parse_blob_columns('["photo", "thumb"]', "legacy")
        self.assertEqual(cols, ["photo", "thumb"])

    def test_parse_blob_columns_falls_back_to_single(self):
        self.assertEqual(parse_blob_columns("", "photo"), ["photo"])

    def test_primary_blob_column(self):
        self.assertEqual(primary_blob_column('["photo", "thumb"]', "legacy"), "photo")

    def test_serialize_blob_columns(self):
        self.assertEqual(serialize_blob_columns(["photo", "thumb"]), '["photo", "thumb"]')

    def test_normalize_object_type(self):
        self.assertEqual(normalize_object_type("VIEW"), OBJECT_TYPE_VIEW)
        self.assertEqual(normalize_object_type("table"), OBJECT_TYPE_TABLE)
