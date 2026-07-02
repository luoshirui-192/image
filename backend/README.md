# 后端服务（Django）

## 目录结构

```
backend/
├── manage.py
├── requirements.txt
├── .env.example          # 复制为 .env 后修改
├── config/               # 项目配置
│   ├── settings.py
│   ├── urls.py
│   └── views.py          # /api/health/
├── users/                # 用户认证
├── images/               # 图片上传、读取、管理
├── sqlquery/             # SQL 查询
├── logs/                 # 操作日志
└── utils/                # 公共工具（路径、安全、响应）
```

## 快速开始

```bash
cd backend
pip install -r requirements.txt
copy .env.example .env    # Windows
# 编辑 .env：MySQL 连接或 DB_ENGINE=sqlite 本地调试

python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

> **若 runserver 提示 “You have N unapplied migration(s)”**  
> 说明尚未执行 `migrate`。在项目目录运行一次即可。

业务表（`sys_user`、`image_info` 等）由 `sql/image_db.sql` 创建，`managed=False` 不会被 migrate 修改。

## 验证

| 地址 | 说明 |
|------|------|
| http://127.0.0.1:8000/api/health/ | 健康检查（无需登录） |
| http://127.0.0.1:8000/api/docs/ | Swagger API 文档 |
| http://127.0.0.1:8000/admin/ | Django Admin |

## 环境变量

见 [`.env.example`](.env.example)。关键项：

- `DB_ENGINE`：`mysql`（生产）或 `sqlite`（本地无 MySQL 时）
- `DB_CHARSET`：MySQL **5.1.x 必须为 `utf8`**
- `UPLOAD_ROOT`：默认指向项目根目录 `upload/`
- `IMAGE_ACCESS_SECRET`：图片访问令牌密钥

## MySQL 5.1 兼容说明

项目已内置 `config/db_backend/` 兼容 MySQL 5.1（`datetime(6)` 降级、`SET NAMES utf8` 等）。

`.env` 中请保持：

```env
DB_ENGINE=mysql
DB_CHARSET=utf8
```

**长期建议**：生产环境升级到 MySQL 5.7+ 或 8.0。

### migrate 报错 errno 150

业务表为 **MyISAM**，Django 默认外键会失败。项目已在 `config/db_backend/features.py` 设置 `supports_foreign_keys = False`。

若 migrate 已中断：

```bash
mysql -h192.168.1.154 -P3306 -u用户名 -p image_db < sql/fix_django_migrate.sql
python manage.py migrate
```

## Model 说明

所有业务表使用 `managed = False`，映射已有 MySQL 表。Django 内置表（sessions 等）仍由 migrate 创建。

## API 概览

### 认证

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/auth/login/` | 公开 | 登录 |
| GET | `/api/auth/me/` | 需登录 | 当前用户 |
| POST | `/api/auth/refresh/` | 公开 | 刷新令牌 |

### 图片上传与分类

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/images/upload/` | 需登录 | 单/多文件上传 |
| POST | `/api/images/import/` | 管理员 | 扫描本地目录批量导入 |
| GET/POST | `/api/images/categories/` | 见接口 | 分类列表/新建 |
| GET/PATCH/DELETE | `/api/images/categories/{id}/` | 见接口 | 分类详情/更新/删除 |

上传后写入 `upload/{YYYYMMDD}/{category_id}/{uuid}.{suffix}`。

### 图片资源读取

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/images/file/` | 登录或 token | 原图预览 |
| GET | `/api/images/thumb/` | 登录或 token | 缩略图 |
| GET | `/api/images/download/` | 登录或 token | 原图下载 |
| GET | `/api/images/access-token/` | 需登录 | 签发短期访问令牌 |

### 图片管理

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/images/` | 需登录 | 分页列表 + 筛选 |
| GET | `/api/images/{id}/` | 需登录 | 详情 |
| PATCH | `/api/images/{id}/` | 需登录 | 更新名称/分类/标签 |
| DELETE | `/api/images/{id}/` | 需登录 | 逻辑删除 |

### SQL 查询

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/sql/execute/` | 管理员 | 执行 SELECT |
| POST | `/api/sql/validate/` | 管理员 | 仅校验 SQL |

仅允许 `SELECT`，禁止 DDL/DML 与多语句。默认最大 1000 行、超时 10 秒。

### 操作日志

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/logs/` | 管理员 | 分页查询 |
| GET | `/api/logs/stats/` | 管理员 | 图片/磁盘统计 |

### 定时维护

```bash
python manage.py cleanup_deleted_images      # 清理已逻辑删除的物理文件
python manage.py purge_old_logs              # 清理过期操作日志
python manage.py cleanup_thumb_cache         # 清理孤儿缩略图缓存
python manage.py run_scheduled_maintenance   # 一键执行
```

| 变量 | 默认 | 说明 |
|------|------|------|
| `DELETED_IMAGE_RETENTION_DAYS` | 30 | 逻辑删除后保留天数 |
| `LOG_RETENTION_DAYS` | 90 | 操作日志保留天数 |

## 测试

MySQL 5.1 不支持 Django 测试库迁移，本地跑单元测试请使用 SQLite：

```bash
set DB_ENGINE=sqlite
python manage.py test -v 2 --noinput
```

## 前端

```bash
cd frontend
npm install
npm run dev
```

访问 http://127.0.0.1:5173 ，详见 [frontend/README.md](../frontend/README.md)
