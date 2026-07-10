# 图像路径式数据库管理系统 — 代码逐文件导读

> **怎么用这份文档：** 按章节顺序阅读；每个文件先读「文件作用」，再对照仓库里的源文件看「逐行/逐块说明」。  
> **关于「每一行」：** 小文件（约 ≤80 行）尽量逐行列出；大文件按**行号区间**分块，块内每一行都有说明，避免重复贴整文件。  
> **有疑问：** 记下「文件路径 + 行号」来问即可。

---

## 系统是什么

这是一个 **Web 应用**：把图片存成磁盘/MinIO 上的**相对路径**，在 MySQL 里只存元数据；支持：

- 本地上传图片（按分类分目录）
- 从旧库 **BLOB 字段迁移** 到路径存储
- **数据库模拟**：像 Navicat 一样浏览外部/本库表，BLOB 列显示为已迁移路径并预览
- 同页 **SQL 查询**
- 管理员：操作日志、系统设置

**技术栈：** Django REST + JWT · Vue 3 + Element Plus · MySQL · Nginx/Gunicorn · 可选 MinIO

---

## 架构一图

```
浏览器 (Vue SPA)
    │  HTTPS /api/*
    ▼
Nginx (web 容器) ──反代──► Gunicorn (backend 容器, Django)
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
                 MySQL    upload/     MinIO (可选)
                 image_db  或 S3      Machine B
                    │
                 legacy DB (外部连接, BLOB 源)
```

**容器（Machine A 生产）：**

| 场景 | Compose | 运行的容器 |
|------|---------|------------|
| 内置 Docker MySQL | `docker-compose.app.yml` | `db` + `backend` + `scheduler` + `web` |
| **宿主机已有 MySQL**（常见） | 上述 + `docker-compose.app.override.yml` | **仅** `backend` + `scheduler` + `web`（`db` 在 profile `with-local-mysql` 下不启动） |

> 机器 A 若本机 3306 已被 MySQL 占用，**必须**使用 override，否则会报 `address already in use`。

**推荐启动命令（宿主机 MySQL）：**

```bash
python3 docker/set-env.py
docker compose -f docker-compose.app.yml -f docker-compose.app.override.yml up -d --build
```

**BLOB 迁移并发：** 默认 `BLOB_MIGRATION_UPLOAD_WORKERS=1`，避免旧库 `Too many connections`。

---

## 推荐阅读顺序

| 章 | 文件 | 内容 |
|----|------|------|
| 0 | 本文 | 总览与索引 |
| 1 | [01-根目录与部署入口.md](./01-根目录与部署入口.md) | README、docker-compose、start 脚本、.env |
| 2 | [02-后端配置与公共工具.md](./02-后端配置与公共工具.md) | `config/`、`utils/`、`manage.py` |
| 3 | [03-后端用户认证与日志SQL.md](./03-后端用户认证与日志SQL.md) | `users/`、`logs/`、`sqlquery/` |
| 4 | [04-后端数据模型与图片核心.md](./04-后端数据模型与图片核心.md) | `images/models.py`、上传、分类、serve |
| 5 | [05-后端BLOB迁移与目录浏览.md](./05-后端BLOB迁移与目录浏览.md) | 迁移服务、任务队列、catalog、table view API |
| 6 | [06-后端命令行与测试.md](./06-后端命令行与测试.md) | `management/commands/`、tests |
| 7 | [07-前端入口路由与布局.md](./07-前端入口路由与布局.md) | `main.js`、router、layout、api、stores |
| 8 | [08-前端页面组件上.md](./08-前端页面组件上.md) | Login、Home、Upload、Category、Settings、Logs |
| 9 | [09-前端页面组件下.md](./09-前端页面组件下.md) | BlobMigrate、BlobTableViews、公共组件 |
| 10 | [10-脚本SQL与Docker.md](./10-脚本SQL与Docker.md) | `scripts/`、`sql/`、`docker/`、`deploy/` |

---

## 全项目文件清单（不含 node_modules / 构建产物）

### 根目录

| 文件/目录 | 作用 |
|-----------|------|
| `README.md` | 项目主文档 |
| `README-MACHINE-A.md` / `README-MACHINE-B.md` | 双机部署说明 |
| `docker-compose.yml` | 开发一体化 compose |
| `docker-compose.app.yml` | 生产 Machine A compose |
| `start*.sh` / `start*.ps1` | 一键启动脚本 |
| `.env*.example` | 环境变量模板 |
| `upload/` | 本地存储根（运行时图片） |
| `import_data/` | 示例 BLOB 导入数据 |

### backend/

| 目录 | 作用 |
|------|------|
| `config/` | Django 项目配置、URL 总路由 |
| `users/` | 登录、JWT、用户模型 |
| `images/` | **核心业务**：图片、迁移、浏览、目录 |
| `sqlquery/` | SQL 执行与模板 |
| `logs/` | 操作审计日志 |
| `utils/` | 存储、路径、安全、SQL 校验 |

### frontend/

| 目录 | 作用 |
|------|------|
| `src/views/` | 各页面 |
| `src/components/` | 可复用 UI 组件 |
| `src/api/` | 后端 HTTP 封装 |
| `src/router/` | 路由与鉴权守卫 |
| `src/layouts/` | 主框架（侧栏+内容区） |
| `src/config/` | 菜单、应用常量 |

---

## 关键数据流（对照代码看）

### 1. 上传一张图

1. `Upload.vue` 选分类 + 文件 → `uploadImagesApi()`（`api/images.js`）
2. `POST /api/images/upload/` → `ImageUploadView`（`images/views.py`）
3. `services.save_uploaded_image()` 校验 → `path_builder.build_relative_path()` 生成路径
4. `storage.save_bytes()` 写 local 或 MinIO → 插入 `image_info` 行

### 2. BLOB 迁移一行

1. `BlobMigrate.vue` 保存迁移源 + 启动任务
2. `POST /api/images/blob-migration/jobs/` → `blob_migration_job_service`
3. `scheduler` 容器循环调用 `process_blob_migration_jobs` 命令
4. `blob_migration_service.run_blob_migration()` 读源库 BLOB → 写 upload → `image_source_map` 记录映射

### 3. 数据库模拟浏览

1. `BlobTableViews.vue` 懒加载目录树 → `blob-catalog/*` API
2. 选中已保存配置 → `GET blob-browse/{id}/rows/`
3. 后端分页读视图行；对 BLOB 列先查基表是否有非空 BLOB，再查 `image_source_map` 组装 path 对象（`migrated` / `pending` / `no_data` / `deleted`）
4. 前端 `ImagePreview` 用 id/path 拉缩略图；无图行显示「无数据」

---

## 阅读格式

除仓库内 Markdown 源稿外，已合并导出 **`code-walkthrough.docx`**（同目录），可用 Word 阅读，无需打开多个 `.md` 文件。重新生成：

```powershell
powershell -File scripts/build_walkthrough_docx.ps1
```

---

## 符号说明

文档中的表格列：

| 列 | 含义 |
|----|------|
| 行 | 源文件行号（1-based） |
| 代码 | 该行主要内容（缩略） |
| 说明 | 该行在做什么、为何需要 |

---

**下一步：** 打开 [01-根目录与部署入口.md](./01-根目录与部署入口.md)，从仓库最外层开始对照阅读。
