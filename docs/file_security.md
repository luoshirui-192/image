# 文件安全规范

## 目标

| 风险 | 对策 |
|------|------|
| 上传 exe/php 等恶意文件 | 扩展名白名单 + 魔数校验 + MIME 校验 |
| 路径穿越 `../../etc/passwd` | 前缀强制 `upload/` + 正则格式 + resolve 后目录边界检查 |
| 未登录访问原图 | 登录态 **或** 有效 HMAC 访问令牌 |

## 代码入口

[`backend/utils/file_security.py`](../backend/utils/file_security.py)

## 1. 上传校验

```python
from utils.file_security import validate_upload_file

result = validate_upload_file(
    filename="photo.jpg",
    content=file_bytes,
    max_bytes=20 * 1024 * 1024,
    declared_mime="image/jpeg",  # 可选
)
# result.suffix, result.mime_type, result.size
```

**规则：**

- 允许扩展名：`jpg` / `jpeg` / `png` / `gif` / `webp` / `bmp`
- 禁止：`exe` / `php` / `jsp` / `sh` / `bat` 等（见 `BLOCKED_EXTENSIONS`）
- 魔数必须与扩展名一致（防止 `shell.php` 改名为 `shell.jpg`）
- 默认大小上限：**20 MB**

## 2. 路径安全

```python
from utils.file_security import resolve_safe_upload_file

abs_path = resolve_safe_upload_file(upload_root, relative_path)
```

**拒绝示例：**

```
upload/../etc/passwd
upload/20260630/1/../../secret.jpg
../../image_db.sql
upload/%2e%2e/admin
```

**通过示例：**

```
upload/20260630/2/550e8400-e29b-41d4-a716-446655440001.jpg
```

流程：`assert_safe_relative_path` → `resolve_upload_file` → `relative_to(upload_base)` 边界检查。

## 3. 图片访问鉴权

```python
from utils.file_security import (
    check_image_access_allowed,
    create_image_access_token,
)

# API 读取原图前
check_image_access_allowed(
    relative_path,
    is_authenticated=request.user.is_authenticated,
    access_token=request.GET.get("token"),
    secret=settings.IMAGE_ACCESS_SECRET,
)

# 为未登录用户生成临时链接（如邮件/分享）
token = create_image_access_token(relative_path, secret, ttl_seconds=3600)
url = f"/api/images/file?path={relative_path}&token={token}"
```

| 访问者 | 条件 |
|--------|------|
| 已登录用户 | 直接允许 |
| 匿名用户 | 必须携带有效 `token`，且 token 绑定路径与过期时间 |

令牌格式：`{expires_at}.{hmac_sha256_signature}`

## 4. 异常类型

| 异常 | 场景 |
|------|------|
| `UploadValidationError` | 上传校验失败 |
| `PathSecurityError` | 非法路径 / 目录穿越 |
| `AccessDeniedError` | 未授权访问图片 |

## 5. 自测

```bash
python scripts/test_file_security.py
```

## 环境变量

```env
MAX_UPLOAD_SIZE_MB=20
IMAGE_ACCESS_SECRET=change-me-in-production
IMAGE_ACCESS_TOKEN_TTL=3600
```
