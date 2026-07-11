#!/usr/bin/env bash
# 机器 A 一键诊断：表数据「已加载 0」、502、登录失败
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "========== 1. .env 数据库配置 =========="
grep -E '^(DB_HOST|DB_PASSWORD|MYSQL_DATABASE|MYSQL_USER|MYSQL_PASSWORD|USE_EXTERNAL_MYSQL)=' .env 2>/dev/null || echo "缺少 .env"

echo ""
echo "========== 2. compose 启动参数 =========="
bash scripts/compose-app-args.sh 2>&1 || true

echo ""
echo "========== 3. 容器状态 =========="
COMPOSE_ARGS=()
while IFS= read -r line; do COMPOSE_ARGS+=("$line"); done < <(bash scripts/compose-app-args.sh 2>/dev/null)
docker compose "${COMPOSE_ARGS[@]}" ps -a 2>/dev/null || docker compose -f docker-compose.app.yml ps -a

echo ""
echo "========== 4. backend 实际连哪台库 =========="
docker compose "${COMPOSE_ARGS[@]}" exec -T backend env 2>/dev/null | grep -E '^DB_' || echo "backend 未运行"

DB_HOST="$(docker compose "${COMPOSE_ARGS[@]}" exec -T backend printenv DB_HOST 2>/dev/null | tr -d '\r' || echo "")"
DB_NAME="$(docker compose "${COMPOSE_ARGS[@]}" exec -T backend printenv DB_NAME 2>/dev/null | tr -d '\r' || echo "")"
DB_USER="$(docker compose "${COMPOSE_ARGS[@]}" exec -T backend printenv DB_USER 2>/dev/null | tr -d '\r' || echo "")"
DB_PASSWORD="$(docker compose "${COMPOSE_ARGS[@]}" exec -T backend printenv DB_PASSWORD 2>/dev/null | tr -d '\r' || echo "")"

echo ""
echo "========== 5. 宿主机 mysql8039 =========="
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E 'mysql8039|NAMES' || echo "无 mysql8039"

echo ""
echo "========== 6. 业务库行数（backend 视角）=========="
if [ -n "$DB_HOST" ] && [ -n "$DB_NAME" ]; then
  docker compose "${COMPOSE_ARGS[@]}" exec -T backend python - <<PY 2>/dev/null || echo "无法连接数据库"
import os, MySQLdb
conn = MySQLdb.connect(
    host=os.environ.get("DB_HOST","db"),
    port=int(os.environ.get("DB_PORT","3306")),
    user=os.environ["DB_USER"],
    passwd=os.environ["DB_PASSWORD"],
    db=os.environ["DB_NAME"],
)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM sys_user")
print("sys_user 行数:", cur.fetchone()[0])
cur.execute("SELECT id,name,database_name,source_table,where_clause FROM blob_table_view ORDER BY id")
rows = cur.fetchall()
print("blob_table_view 配置数:", len(rows))
for r in rows[:10]:
    print(" ", r)
PY
fi

echo ""
echo "========== 7. 健康检查 =========="
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1/api/health/ 2>/dev/null || echo "无法访问 /api/health/"

echo ""
echo "========== 结论 =========="
if [ "$DB_HOST" = "db" ]; then
  echo "❌ backend 连的是 compose 内置 db（多为空库）→ 表数据会「已加载 0」"
  echo "   修复: .env 设 DB_HOST=host.docker.internal，然后 ./start-app.sh"
elif [ "$DB_HOST" = "host.docker.internal" ]; then
  echo "✓ backend 指向宿主机 MySQL"
else
  echo "? DB_HOST=$DB_HOST"
fi
