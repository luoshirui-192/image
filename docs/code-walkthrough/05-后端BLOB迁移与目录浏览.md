# 第 5 章：后端 BLOB 迁移与目录浏览

---

## `blob_migration_service.py` — 函数级地图

| 行号约 | 符号 | 作用 |
|--------|------|------|
| 36-72 | 异常/结果 dataclass | 结构化迁移结果统计 |
| 74-100 | `_close_worker_connections` / `_upload_workers` | 线程结束关闭全部 DB 连接；默认 worker=1 |
| 92-123 | `_record_job_error` / `_update_job_progress` | 更新 job 表进度 |
| 125-146 | `validate_*` | 防 SQL 注入：标识符、WHERE、db_alias |
| 148-207 | `discover_blob_tables` | 扫描库中含 BLOB 的表 |
| 519-558 | `_fetch_blob_from_lookup_table` | JOIN 视图：从基表按 `Fname` 等键读 BLOB |
| 781-839 | `_prepare_migration_batch` | 单会话批处理：扫 PK → 查 map → 按需拉 BLOB |
| 908+ | `_migrate_single_column` | 单列迁移：写 storage + image_info + source_map |
| 1145+ | `_run_migration_batch_cursor` | **任务主循环**：单旧库连接；worker>1 时主线程预取 BLOB 再并行上传 |
| 1357+ | `count_migration_candidates` | 统计待迁数；JOIN 视图按「有键列×列数」估算，非实查基表 BLOB |

**连接数注意：** 勿将 `BLOB_MIGRATION_UPLOAD_WORKERS` 设过大；并行线程曾导致旧库 `(1040, Too many connections)`。

**单条迁移核心逻辑（`_migrate_single_column`）：**

1. 读 BLOB bytes（视图列或 `path_mappings` 指向的基表）
2. 空 BLOB → `skipped`（不算失败）
3. `build_relative_path` → `storage.save_bytes` → `image_info` → `image_source_map`

---

## `blob_migration_job_service.py`（360 行）

| 职责 | 说明 |
|------|------|
| `create_job` | 插入 pending job |
| `process_pending_jobs` | scheduler 调用：取 pending→running |
| `cancel_job` | 设 `cancel_requested` |
| `clear_history` | 清理已完成 job |

---

## `blob_catalog_service.py`（219 行）

| 函数 | API 对应 |
|------|----------|
| `list_connections` | GET `blob-catalog/connections/` — default + legacy + external 汇总 |
| `list_databases` | GET `blob-catalog/databases/` |
| `list_objects` | GET `blob-catalog/objects/` — 表/视图 + blob_columns |
| `get_object_detail` | GET `blob-catalog/objects/{name}/` — 列信息、PK |

懒加载树：**前端 el-tree lazy load 三次调用上述接口**。

---

## `blob_table_view_service.py`

| 函数 | 作用 |
|------|------|
| `fetch_view_rows` | 分页读源表；自动 SELECT `path_mappings` 需要的关联列（如 `src_fname`） |
| `_compute_blob_presence_for_page` | 批量查基表 `LENGTH(blob)>0`，区分无图与未迁 |
| `_build_path_cell` | 查 `image_source_map` 组装 path 对象 |
| `_load_path_maps_for_mappings` | JOIN 视图按 `lookup_table` + 文件名查映射 |

**path 对象形状（前端 `pathCell()` 依赖）：**

```json
{
  "display": "upload/.../xxx.jpg | 未迁移 | 无数据 | 已删除",
  "path": "upload/.../xxx.jpg",
  "status": "migrated | pending | no_data | deleted",
  "image_info_id": 123
}
```

| status | 含义 |
|--------|------|
| `migrated` | 已写入 `image_source_map` 且图未删 |
| `pending` | 基表有 BLOB，尚未迁移 |
| `no_data` | 基表无 BLOB 或关联不到（**不是**未迁移） |
| `deleted` | 映射存在但 `image_info.is_delete=1` |

---

## `external_db_service.py`（426 行）

外部连接 CRUD、密码加密、测试连接、`mysql.connector` 动态连接。

---

## `blob_view_path_service.py`

预览 schema：不迁移动作下推断列类型。

---

## `schema_ensure.py`（273 行）

启动时检查并 CREATE TABLE IF NOT EXISTS 迁移相关表（Docker entrypoint 也会跑）。

---

## 视图层文件对照

| 文件 | 职责 |
|------|------|
| `blob_migration_views.py` | HTTP 绑定 migration/job |
| `blob_catalog_views.py` | HTTP 绑定 catalog |
| `blob_table_view_views.py` | HTTP 绑定 browse rows |
| `external_db_views.py` | HTTP 绑定 external connection |
| `serializers.py` | 请求/响应 JSON 形状 |

---

下一章：[06-后端命令行与测试.md](./06-后端命令行与测试.md)
