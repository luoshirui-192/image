"""SQL validator unit tests — Step 13."""
from django.test import SimpleTestCase, override_settings

from utils.security_test_fixtures import (
    sql_delete_from_images,
    sql_drop_table,
    sql_injection_payloads,
)
from utils.sql_validator import SqlValidationError, validate_sql


class SqlValidatorTestCase(SimpleTestCase):
    def test_allows_simple_select(self):
        sql = validate_sql("SELECT id, image_path FROM image_info WHERE is_delete = 0")
        self.assertIn("SELECT", sql.upper())

    def test_rejects_empty(self):
        with self.assertRaises(SqlValidationError):
            validate_sql("   ")

    def test_rejects_delete(self):
        with self.assertRaises(SqlValidationError):
            validate_sql(sql_delete_from_images())

    def test_rejects_drop(self):
        with self.assertRaises(SqlValidationError):
            validate_sql(sql_drop_table())

    def test_rejects_insert(self):
        with self.assertRaises(SqlValidationError):
            validate_sql("INSERT INTO image_info (image_name) VALUES ('x')")

    def test_rejects_update(self):
        with self.assertRaises(SqlValidationError):
            validate_sql("UPDATE image_info SET tags='x'")

    def test_rejects_multiple_statements(self):
        with self.assertRaises(SqlValidationError):
            validate_sql(sql_injection_payloads()[0][1])

    def test_rejects_sleep(self):
        with self.assertRaises(SqlValidationError):
            validate_sql(sql_injection_payloads()[4][1])

    def test_strips_comments(self):
        sql = validate_sql("SELECT 1 -- comment\nFROM image_info")
        self.assertIn("image_info", sql)

    @override_settings()
    def test_select_star_without_where_optional(self):
        validate_sql("SELECT * FROM image_info", require_where_for_select_star=False)

    def test_select_star_without_where_strict(self):
        with self.assertRaises(SqlValidationError):
            validate_sql("SELECT * FROM image_info", require_where_for_select_star=True)

    def test_select_star_with_where_allowed_in_strict(self):
        validate_sql(
            "SELECT * FROM image_info WHERE id = 1",
            require_where_for_select_star=True,
        )

    def test_column_name_with_update_substring(self):
        validate_sql("SELECT update_time FROM image_info")
