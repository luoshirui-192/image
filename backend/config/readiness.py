"""Production readiness checks for /api/health/."""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db import connection

from utils.storage import get_image_storage


def _upload_root() -> Path:
    return Path(settings.UPLOAD_ROOT).resolve()


def check_database() -> tuple[bool, str]:
    if settings.DB_ENGINE == "sqlite":
        return False, "生产环境应使用 DB_ENGINE=mysql"
    try:
        from images.external_db_service import ensure_system_database_names, expected_system_db_name

        repaired = ensure_system_database_names()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
            current_db = ""
            if connection.vendor == "mysql":
                cursor.execute("SELECT DATABASE()")
                row = cursor.fetchone()
                current_db = str(row[0] or "") if row else ""
                expected = expected_system_db_name("default") or ""
                if expected and current_db and current_db != expected:
                    return False, f"当前库={current_db} 期望={expected}"
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name = 'image_info'"
                )
                if int(cursor.fetchone()[0] or 0) < 1:
                    return False, f"当前库 {current_db or '?'} 缺少 image_info"
        detail = "ok"
        if current_db:
            detail = f"ok ({current_db})"
        if repaired:
            detail = f"{detail}; repaired={','.join(repaired)}"
        return True, detail
    except Exception as exc:
        return False, str(exc)


def check_upload_writable() -> tuple[bool, str]:
    if getattr(settings, "STORAGE_BACKEND", "local").lower() == "minio":
        return get_image_storage().check_writable()
    root = _upload_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, str(root)
    except Exception as exc:
        return False, str(exc)


def check_thumb_cache_writable() -> tuple[bool, str]:
    root = Path(settings.THUMB_CACHE_ROOT).resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, str(root)
    except Exception as exc:
        return False, str(exc)


def check_secrets() -> tuple[bool, list[str]]:
    issues: list[str] = []
    insecure_markers = (
        "dev-insecure",
        "change-me",
        "请替换",
    )
    for name, value in (
        ("SECRET_KEY", settings.SECRET_KEY),
        ("IMAGE_ACCESS_SECRET", settings.IMAGE_ACCESS_SECRET),
    ):
        text = str(value or "")
        if not text:
            issues.append(f"{name} 未设置")
            continue
        if any(marker in text for marker in insecure_markers):
            issues.append(f"{name} 仍为默认值，请更换")

    if getattr(settings, "STORAGE_BACKEND", "local").lower() == "minio":
        for name, value in (
            ("MINIO_ACCESS_KEY", settings.MINIO_ACCESS_KEY),
            ("MINIO_SECRET_KEY", settings.MINIO_SECRET_KEY),
        ):
            if not str(value or "").strip():
                issues.append(f"{name} 未设置")
        if not str(settings.MINIO_ENDPOINT or "").strip():
            issues.append("MINIO_ENDPOINT 未设置")

    return len(issues) == 0, issues


# Skip frontend_dist in Docker backend image (frontend lives in nginx container).
def check_frontend_dist() -> tuple[bool, str]:
    from pathlib import Path as _Path

    if _Path("/.dockerenv").exists():
        return True, "skipped-in-backend-container"
    dist = settings.PROJECT_ROOT / "frontend" / "dist" / "index.html"
    if dist.is_file():
        return True, str(dist.parent)
    return False, str(dist.parent)


def check_image_probe() -> dict:
    """Sample one live ImageInfo row and verify DB path + object storage."""
    from images.external_db_service import ensure_system_database_names
    from images.models import ImageInfo
    from utils.file_security import PathSecurityError, assert_safe_relative_path

    ensure_system_database_names()
    result: dict = {
        "ok": False,
        "image_info_count": 0,
        "sample_id": None,
        "sample_path": None,
        "path_ok": False,
        "storage_exists": False,
        "storage_read_ok": False,
        "detail": "",
    }
    try:
        result["image_info_count"] = ImageInfo.objects.filter(is_delete=0).count()
        sample = (
            ImageInfo.objects.filter(is_delete=0)
            .exclude(image_path="")
            .order_by("-id")
            .only("id", "image_path")
            .first()
        )
        if sample is None:
            result["detail"] = "image_info 无可用记录"
            return result

        result["sample_id"] = sample.id
        result["sample_path"] = sample.image_path
        try:
            safe = assert_safe_relative_path(sample.image_path)
            result["path_ok"] = True
        except PathSecurityError as exc:
            result["detail"] = f"路径校验失败: {exc}"
            return result

        storage = get_image_storage()
        result["storage_backend"] = storage.backend_name
        if storage.backend_name == "minio":
            result["storage_key"] = storage._object_key(safe)  # noqa: SLF001 — diagnostic only
        exists = storage.exists(safe)
        result["storage_exists"] = bool(exists)
        if not exists:
            result["detail"] = "对象存储中不存在该文件"
            return result
        data = storage.read_bytes(safe)
        result["storage_read_ok"] = bool(data)
        result["sample_bytes"] = len(data)
        result["ok"] = True
        result["detail"] = "ok"
        return result
    except Exception as exc:
        result["detail"] = str(exc)
        return result


def collect_readiness() -> dict:
    db_ok, db_detail = check_database()
    upload_ok, upload_detail = check_upload_writable()
    thumb_ok, thumb_detail = check_thumb_cache_writable()
    secrets_ok, secret_issues = check_secrets()
    dist_ok, dist_detail = check_frontend_dist()
    image_probe = check_image_probe()

    checks = {
        "debug": settings.DEBUG,
        "storage_backend": getattr(settings, "STORAGE_BACKEND", "local"),
        "database": {"ok": db_ok, "detail": db_detail},
        "upload_writable": {"ok": upload_ok, "path": upload_detail},
        "thumb_cache_writable": {"ok": thumb_ok, "path": thumb_detail},
        "secrets": {"ok": secrets_ok, "issues": secret_issues},
        "frontend_dist": {"ok": dist_ok, "path": dist_detail},
        "image_probe": image_probe,
    }
    image_ok = bool(image_probe.get("ok")) or int(image_probe.get("image_info_count") or 0) == 0
    checks["ready"] = (
        not settings.DEBUG
        and db_ok
        and upload_ok
        and thumb_ok
        and secrets_ok
        and dist_ok
        and image_ok
    )
    return checks
