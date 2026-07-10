# 第 3 章：后端用户认证、日志与 SQL

---

## `backend/users/` 应用

### `models.py` — SysUser

| 字段 | 说明 |
|------|------|
| `username` | 登录名 |
| `password_hash` | 密码（非 Django 默认字段名） |
| `role` | `admin` / 普通用户 |
| `Meta.managed = False` | 表由 `sql/image_db.sql` 创建，Django 不 migrate 业务表 |

### `views.py`

| 视图 | 路由 | 行级逻辑 |
|------|------|----------|
| LoginView | POST `/api/auth/login/` | 校验用户名密码 → 签发 JWT access+refresh |
| RefreshView | POST `/api/auth/refresh/` | 用 refresh 换新 access |
| MeView | GET `/api/auth/me/` | 返回当前用户 `{username, role, is_admin}` |

### `urls.py`

三行 `path()` 对应上面三个视图。

### `serializers.py`

Login 请求体校验、Me 响应字段序列化。

---

## `backend/logs/` 应用

### `models.py` — OperateLog

| 字段 | 说明 |
|------|------|
| `user_name` | 操作者 |
| `operate_type` | 如 `upload`、`sql_execute`、`category_create` |
| `operate_detail` | 文本详情 |
| `operate_time` | 时间戳 |
| `ip_address` | 客户端 IP |

### `views.py`

| 视图 | 说明 |
|------|------|
| OperateLogListView | 分页列表，管理员可筛 type/时间 |
| StorageStatsView | 存储统计（图片数、按分类计数） |

### `management/commands/purge_old_logs.py`

按 `LOG_RETENTION_DAYS` 删除过期日志；scheduler 定期调用。

---

## `backend/sqlquery/` 应用

### `services.py`（142 行）

| 函数 | 行号区间（约） | 作用 |
|------|----------------|------|
| `get_connection_params` | 开头 | 从 `dbAlias`/`connectionId` 解析用哪个 DB |
| `execute_sql` | 中部 | 设置 `max_execution_time`，执行 SELECT，截断行数 |
| `validate_sql` | | 只解析不执行，走 validator |

**安全要点：** 仅允许 SELECT；连接可指向 default 或 legacy 或 external。

### `views.py`

| 路由 | 视图 |
|------|------|
| POST `/api/sql/execute/` | 执行 |
| POST `/api/sql/validate/` | 校验 |

请求体含 `sql` + `db_alias` / `database` / `connection_id`（与前端 `browseContext` 一致）。

### `template_store.py`

读写 `backend/data/sql_templates.json` — 保存常用 SQL 模板。

### `templates_views.py`

模板 CRUD API（若前端使用）。

---

## 与前端对应关系

| 前端文件 | 后端 |
|----------|------|
| `stores/auth.js` | `users/views.py` |
| `api/auth.js` | `/api/auth/*` |
| `views/Logs.vue` | `logs/views.py` |
| `BlobTableViews.vue` SQL 标签 | `sqlquery/services.py` |
| `api/sql.js` | `/api/sql/*` |

---

下一章：[04-后端数据模型与图片核心.md](./04-后端数据模型与图片核心.md)
