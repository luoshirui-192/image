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
| `/import` | 批量导入（管理员） |
| `/sql` | SQL 查询面板（管理员） |
| `/images` | 图片列表 |
| `/categories` | 分类管理（管理员） |
| `/logs` | 操作日志（管理员） |
| `/settings` | 系统设置（管理员） |

## 构建

```bash
npm run build
```

产物输出到 `dist/`。
