# 图片文件存储目录

本目录存放上传的原始图片，**不在数据库中保存二进制**，仅通过 `image_info.image_path` 记录相对路径。

## 分层规则

```
upload/
└── {YYYYMMDD}/          # 按上传日期分目录，便于备份与清理
    └── {category_id}/   # 按分类 ID 分目录
        └── {uuid}.{ext} # UUID 文件名，避免重名冲突
```

**示例：**

```
upload/20260630/2/550e8400-e29b-41d4-a716-446655440001.jpg
         │        │  └─ 唯一文件名
         │        └─ 分类 ID（对应 image_category.id）
         └─ 上传日期
```

**相对路径格式（写入数据库）：**

```
upload/{YYYYMMDD}/{category_id}/{uuid}.{suffix}
```

## 使用方式

Python 路径生成见 [`backend/utils/path_builder.py`](../backend/utils/path_builder.py)。

初始化目录并检查可写性：

```bash
python scripts/init_storage.py
```

## 注意事项

- 路径统一使用正斜杠 `/`，入库时不带 leading slash
- 缩略图缓存目录为 `backend/thumb_cache/`，不在此目录
- 生产环境可通过 Nginx 将 `/upload/` 映射到此目录
- 上传校验、路径穿越防护、访问令牌见 [`docs/file_security.md`](../docs/file_security.md)
