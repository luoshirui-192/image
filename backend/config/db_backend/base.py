from functools import cached_property
import re

from django.db.backends.mysql.base import DatabaseWrapper as MySQLDatabaseWrapper

from config.db_backend.features import DatabaseFeatures


def _storage_engine_sql(version: str) -> str:
    """MySQL 5.1 uses @@storage_engine; 5.5.3+ uses @@default_storage_engine."""
    match = re.match(r"(\d+)\.(\d+)", version or "")
    if match and int(match.group(1)) == 5 and int(match.group(2)) <= 1:
        return "@@storage_engine"
    return "@@default_storage_engine"


class DatabaseWrapper(MySQLDatabaseWrapper):
    """MySQL 5.1.x compatibility with optional 5.7+ (Docker) support."""

    features_class = DatabaseFeatures

    # MySQL 5.1 does not support datetime(6) / fractional seconds.
    _data_types = {
        **MySQLDatabaseWrapper._data_types,
        "DateTimeField": "datetime",
        "TimeField": "time",
    }

    def get_new_connection(self, conn_params):
        """
        Handshake uses latin1 (MySQL 5.1 + mysqlclient workaround via init_command SET NAMES utf8).
        Force client-side binding encoding to utf8 without set_character_set (maps to utf8mb3 on 5.1).
        """
        connection = super().get_new_connection(conn_params)
        connection.encoding = "utf8"
        return connection

    @cached_property
    def mysql_server_data(self):
        with self.temporary_connection() as cursor:
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            engine_sql = _storage_engine_sql(version)
            cursor.execute(
                f"""
                SELECT VERSION(),
                       @@sql_mode,
                       {engine_sql},
                       @@sql_auto_is_null,
                       @@lower_case_table_names,
                       0
                """
            )
            row = cursor.fetchone()
        return {
            "version": row[0],
            "sql_mode": row[1],
            "default_storage_engine": row[2],
            "sql_auto_is_null": bool(row[3]),
            "lower_case_table_names": bool(row[4]),
            "has_zoneinfo_database": bool(row[5]),
        }
