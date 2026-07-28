# 文件存储架构

## 设计目标

- 数据库只存**相对路径**，不存图片二进制
- 按**日期 + 分类**分层，避免单目录文件过多
- 文件名使用 **UUID**，避免同名覆盖
- **路径即全局身份**：`upload/...`（或 `templates/...`）唯一对应 MinIO/本地对象；业务库表只是引用，跨库/换表/重建浏览配置后，只要单元格仍是该路径即可预览

## 浏览配置与图片列

- **任意表都可建浏览配置**（与「同步表」一致），不强制必须有图片列。
- 图片列可以是物理 **BLOB**，也可以是存 `upload/...` 的 **路径列**；目录/详情会识别并标出路径列。
- 勾选了图片列才能在浏览页预览；未勾选则只作普通表浏览。

## 目录结构

```
项目根/
├── upload/                          # 原始图片
│   └── {YYYYMMDD}/
│       └── {category_id}/
│           └── {uuid}.{suffix}
└── backend/
    └── thumb_cache/                 # 缩略图缓存
```

## 路径规范

| 项目 | 规则 |
|------|------|
| 入库字段 | `image_info.image_path` |
| 格式 | `upload/{YYYYMMDD}/{category_id}/{uuid}.{suffix}` |
| 分隔符 | 统一 `/`，不带开头 `/` |
| 后缀 | 小写，`jpeg` 规范化为 `jpg` |

示例：

```
upload/20260630/2/550e8400-e29b-41d4-a716-446655440001.jpg
```

## 代码入口

[`backend/utils/path_builder.py`](../backend/utils/path_builder.py)

| 函数 | 用途 |
|------|------|
| `build_relative_path()` | 生成入库相对路径 |
| `resolve_upload_file()` | 相对路径 → 磁盘绝对路径 |
| `ensure_parent_dir()` | 创建目标目录 |
| `is_valid_relative_path()` | 校验路径格式 |
| `parse_relative_path()` | 解析日期、分类、UUID |
| `list_date_dirs()` | 列出日期目录（备份/清理任务用） |

## 初始化

```bash
python scripts/init_storage.py
```

会创建 `upload/`、`backend/thumb_cache/`，并验证目录可写。

## 相关文档

上传/读取安全见 [`file_security.md`](file_security.md)。
