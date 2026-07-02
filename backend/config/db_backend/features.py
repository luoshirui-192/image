from django.db.backends.mysql.features import DatabaseFeatures as MySQLDatabaseFeatures
from django.utils.functional import cached_property


class DatabaseFeatures(MySQLDatabaseFeatures):
    """Relax minimum version check; disable features missing in MySQL 5.1."""

    @cached_property
    def minimum_database_version(self):
        return (5, 1)

    supports_transactions = True
    supports_atomic_references = False
    can_rollback_ddl = False
    # sys_user 等业务表为 MyISAM，不能与 InnoDB 外键混用（errno 150）
    supports_foreign_keys = False
    supports_stored_generated_columns = False
    supports_virtual_generated_columns = False
    supports_update_conflicts = False
    has_zoneinfo_database = False
    supports_over_clause = False

    @cached_property
    def test_collations(self):
        return {
            "ci": "utf8_general_ci",
            "non_default": "utf8_bin",
            "swedish_ci": "utf8_swedish_ci",
            "virtual": "utf8_bin",
        }

    test_now_utc_template = "UTC_TIMESTAMP()"
