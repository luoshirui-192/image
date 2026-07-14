#!/usr/bin/env bash
# 在 192.168.1.33 的 MySQL Docker 容器里：新建系统库 image_db，
# 并把误放在 ara_fp_analyst 里的系统表 RENAME 过去。
#
# 用法（在跑 Docker 的那台机上执行，即 192.168.1.33；或已能 docker 到该机）:
#   export MYSQL_ROOT_PASSWORD='你的容器 root 密码'
#   ./scripts/provision_system_db_docker.sh
#   ./scripts/provision_system_db_docker.sh --yes
#   ./scripts/provision_system_db_docker.sh --container mysql8039
#
# 若在别的机器上，先 ssh 到 1.33 再跑本脚本。

set -euo pipefail

HOST_HINT="192.168.1.33"
WRONG_DB="${WRONG_DB:-ara_fp_analyst}"
SYSTEM_DB="${SYSTEM_DB:-image_db}"
APP_USER="${MYSQL_USER:-image_db}"
APP_PASSWORD="${MYSQL_PASSWORD:-}"
PASSWORD="${MYSQL_ROOT_PASSWORD:-}"
CONTAINER="${MYSQL_CONTAINER:-}"
YES=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --container) CONTAINER="$2"; shift 2 ;;
    --wrong-db) WRONG_DB="$2"; shift 2 ;;
    --system-db) SYSTEM_DB="$2"; shift 2 ;;
    --password) PASSWORD="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

if [[ -z "$PASSWORD" ]]; then
  read -r -s -p "请输入 MySQL 容器 root 密码: " PASSWORD
  echo
fi

if [[ -z "$CONTAINER" ]]; then
  echo "正在查找 MySQL 容器..."
  CONTAINER="$(docker ps --format '{{.Names}}' | grep -E 'mysql|mariadb' | head -n1 || true)"
fi
if [[ -z "$CONTAINER" ]]; then
  echo "未找到运行中的 MySQL 容器。请指定: --container 容器名"
  echo "当前容器列表:"
  docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
  exit 1
fi

echo "============================================================"
echo "Docker 容器: $CONTAINER"
echo "业务库(误):  $WRONG_DB   ← 迁出系统表，业务表保留"
echo "系统库(新):  $SYSTEM_DB  ← 本应用 Django DB_NAME"
echo "提示: MySQL 若在 ${HOST_HINT} 上，请在该机执行本脚本"
echo "============================================================"

if [[ "$YES" != "1" && "$DRY_RUN" != "1" ]]; then
  read -r -p "确认执行？输入 yes 继续: " ans
  [[ "$ans" == "yes" ]] || { echo "已取消"; exit 1; }
fi

mysql_q() {
  # shellcheck disable=SC2016
  docker exec -i "$CONTAINER" mysql -uroot -p"$PASSWORD" -N -e "$1" 2> >(grep -v 'Using a password on the command line' >&2 || true)
}

mysql_exec() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "  [dry-run] $1"
    return 0
  fi
  docker exec -i "$CONTAINER" mysql -uroot -p"$PASSWORD" -e "$1" 2> >(grep -v 'Using a password on the command line' >&2 || true)
}

# 验证连接
if [[ "$DRY_RUN" != "1" ]]; then
  if ! mysql_q "SELECT 1" >/dev/null; then
    echo "无法用 root 连接容器内 MySQL，请检查 MYSQL_ROOT_PASSWORD / 容器名"
    exit 1
  fi
fi

echo
echo "[1] CREATE DATABASE $SYSTEM_DB"
mysql_exec "CREATE DATABASE IF NOT EXISTS \`$SYSTEM_DB\` DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci;"

APP_TABLES=(
  sys_user image_category image_info operate_log
  blob_migration_source image_source_map external_db_connection blob_table_view
  blob_migration_job blob_migration_job_error blob_sync_run
  django_migrations django_content_type django_session django_admin_log
  auth_group auth_group_permissions auth_permission
)

echo
echo "[2] 从 $WRONG_DB RENAME 系统表 → $SYSTEM_DB"
wrong_exists="$(mysql_q "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='$WRONG_DB'" || echo 0)"
if [[ "$wrong_exists" == "0" ]]; then
  echo "  警告: 业务库 $WRONG_DB 不存在，跳过迁表"
else
  for table in "${APP_TABLES[@]}"; do
    in_wrong="$(mysql_q "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$WRONG_DB' AND TABLE_NAME='$table' AND TABLE_TYPE='BASE TABLE'" || echo 0)"
    in_sys="$(mysql_q "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$SYSTEM_DB' AND TABLE_NAME='$table' AND TABLE_TYPE='BASE TABLE'" || echo 0)"
    if [[ "$in_wrong" == "0" ]]; then
      continue
    fi
    if [[ "$in_sys" != "0" ]]; then
      echo "  skip $table (系统库已有)"
      continue
    fi
    echo "  MOVE $WRONG_DB.$table → $SYSTEM_DB.$table"
    mysql_exec "RENAME TABLE \`$WRONG_DB\`.\`$table\` TO \`$SYSTEM_DB\`.\`$table\`;"
  done
fi

echo
echo "[3] 补齐核心空表（若仍缺失）"
mysql_exec "
USE \`$SYSTEM_DB\`;
CREATE TABLE IF NOT EXISTS \`image_category\` (
  \`id\` int(10) UNSIGNED NOT NULL AUTO_INCREMENT,
  \`category_name\` varchar(100) NOT NULL DEFAULT '',
  \`sort\` int(11) NOT NULL DEFAULT 0,
  \`create_time\` datetime NULL DEFAULT NULL,
  PRIMARY KEY (\`id\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
CREATE TABLE IF NOT EXISTS \`sys_user\` (
  \`id\` int(10) UNSIGNED NOT NULL AUTO_INCREMENT,
  \`password\` varchar(128) NOT NULL,
  \`username\` varchar(100) NOT NULL,
  \`role\` varchar(20) NOT NULL DEFAULT 'user',
  \`status\` smallint NOT NULL DEFAULT 1,
  \`create_time\` datetime NULL DEFAULT NULL,
  PRIMARY KEY (\`id\`),
  UNIQUE KEY \`username\` (\`username\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
CREATE TABLE IF NOT EXISTS \`image_info\` (
  \`id\` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  \`image_name\` varchar(255) NOT NULL DEFAULT '',
  \`image_path\` varchar(500) NOT NULL DEFAULT '',
  \`image_width\` int(11) NOT NULL DEFAULT 0,
  \`image_height\` int(11) NOT NULL DEFAULT 0,
  \`file_size\` bigint(20) UNSIGNED NOT NULL DEFAULT 0,
  \`file_suffix\` varchar(20) NOT NULL DEFAULT '',
  \`file_hash\` varchar(64) NOT NULL DEFAULT '',
  \`upload_time\` datetime NOT NULL,
  \`update_time\` datetime NOT NULL,
  \`upload_user\` varchar(100) NOT NULL DEFAULT '',
  \`is_delete\` smallint NOT NULL DEFAULT 0,
  \`category_id\` int(10) UNSIGNED NULL DEFAULT NULL,
  \`tags\` varchar(500) NOT NULL DEFAULT '',
  PRIMARY KEY (\`id\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
CREATE TABLE IF NOT EXISTS \`operate_log\` (
  \`id\` bigint(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  \`user_id\` int(10) UNSIGNED NULL DEFAULT NULL,
  \`username\` varchar(100) NOT NULL DEFAULT '',
  \`action_type\` varchar(20) NOT NULL DEFAULT '',
  \`sql_content\` text NULL,
  \`detail\` varchar(500) NOT NULL DEFAULT '',
  \`ip\` varchar(50) NOT NULL DEFAULT '',
  \`create_time\` datetime NULL DEFAULT NULL,
  PRIMARY KEY (\`id\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
"

# 容器内若挂了仓库 sql，可再执行；这里不强制，靠应用 schema_ensure 补 BLOB 表

echo
echo "[4] 授权应用用户（可选）"
if [[ -n "$APP_USER" && -n "$APP_PASSWORD" ]]; then
  mysql_exec "CREATE USER IF NOT EXISTS '$APP_USER'@'%' IDENTIFIED BY '$APP_PASSWORD';" || true
  mysql_exec "GRANT ALL PRIVILEGES ON \`$SYSTEM_DB\`.* TO '$APP_USER'@'%'; FLUSH PRIVILEGES;"
else
  echo "  未设置 MYSQL_USER/MYSQL_PASSWORD，跳过 CREATE USER（root 或现有账号可连）"
fi

echo
echo "============================================================"
echo "完成。请把应用 .env 改为连系统库:"
echo "  DB_HOST=192.168.1.33   # 或 host.docker.internal / 容器网络主机名"
echo "  MYSQL_DATABASE=$SYSTEM_DB"
echo "  DB_NAME=$SYSTEM_DB"
echo "业务库继续用: $WRONG_DB"
echo "============================================================"
