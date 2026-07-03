#!/bin/bash
# 机器 B：首次启动 MySQL 时导入 sql/ 脚本（含 BLOB 迁移表）
set -e

mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" <<EOF
CREATE DATABASE IF NOT EXISTS \`${MYSQL_DATABASE}\` DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci;
EOF

mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" "${MYSQL_DATABASE}" < /sql/image_db.sql
mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" "${MYSQL_DATABASE}" < /sql/optimize_indexes.sql
mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" "${MYSQL_DATABASE}" < /sql/fix_mysql57_triggers.sql
mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" "${MYSQL_DATABASE}" < /sql/seed_test_data.sql
mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" "${MYSQL_DATABASE}" < /sql/blob_migration.sql

echo "[init-data] database ${MYSQL_DATABASE} ready (with blob_migration tables)"
