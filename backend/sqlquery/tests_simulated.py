"""Tests for SQL cell formatting and simulated query parsing."""
from __future__ import annotations

from django.test import SimpleTestCase

from sqlquery.cell_format import format_blob_placeholder, serialize_sql_cell
from sqlquery.simulated_sql import parse_simulated_select


class SqlCellFormatTestCase(SimpleTestCase):
    def test_blob_placeholder(self):
        self.assertEqual(format_blob_placeholder(0), "[empty BLOB]")
        self.assertEqual(format_blob_placeholder(512), "[BLOB 512 bytes]")
        self.assertIn("KB", format_blob_placeholder(2048))

    def test_serialize_binary(self):
        self.assertEqual(serialize_sql_cell(b"\xff\xd8\xff"), "[BLOB 3 bytes]")

    def test_serialize_path_cell_dict(self):
        cell = {"display": "upload/x.jpg", "path": "upload/x.jpg", "image_info_id": 1, "status": "migrated"}
        self.assertEqual(serialize_sql_cell(cell), cell)


class SqlRewriteTestCase(SimpleTestCase):
    def test_split_select_columns(self):
        from sqlquery.sql_rewrite import _split_select_columns

        parts = _split_select_columns("id, name, COUNT(*) as cnt")
        self.assertEqual(parts, ["id", "name", "COUNT(*) as cnt"])

    def test_parse_simple_column(self):
        from sqlquery.sql_rewrite import _parse_simple_column

        self.assertEqual(_parse_simple_column("`photo`"), ("photo", "photo"))
        self.assertEqual(_parse_simple_column("t.photo AS p"), ("photo", "p"))
        self.assertIsNone(_parse_simple_column("COUNT(*)"))


class SimulatedSqlParseTestCase(SimpleTestCase):
    def test_parse_limit_and_where(self):
        parsed = parse_simulated_select(
            "SELECT * FROM my_table WHERE id > 10 LIMIT 50 OFFSET 100",
            expected_table="my_table",
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.limit, 50)
        self.assertEqual(parsed.offset, 100)
        self.assertEqual(parsed.extra_where, "id > 10")

    def test_reject_wrong_table(self):
        self.assertIsNone(
            parse_simulated_select(
                "SELECT * FROM other_table LIMIT 10",
                expected_table="my_table",
            )
        )
