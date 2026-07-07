# 前端（Vue 3）

## 快速开始

```bash
cd backend && python manage.py runserver 0.0.0.0:8000
cd frontend && npm install && npm run dev
```

访问 http://localhost:5173

## 页面

| 路由 | 说明 |
|------|------|
| `/upload` | 图片上传 |
| `/blob-migrate` | BLOB 迁移 |
| `/blob-browse` | BLOB 数据浏览（表数据 + SQL + 多 BLOB 预览） |
| `/blob-views` | 旧路由，重定向到 `/blob-browse` |
| `/sql`、`/sql-query` | 旧路由，重定向到 `/blob-browse?mode=sql` |
| `/categories` | 分类管理 |
| `/logs` | 操作日志（管理员） |
| `/settings` | 系统设置（管理员） |

## 构建

```bash
npm run build
```

产物输出到 `dist/`。
