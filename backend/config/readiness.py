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
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True, "ok"
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


def check_frontend_dist() -> tuple[bool, str]:
    dist = settings.PROJECT_ROOT / "frontend" / "dist" / "index.html"
    if dist.is_file():
        return True, str(dist.parent)
    return False, str(dist.parent)


def collect_readiness() -> dict:
    db_ok, db_detail = check_database()
    upload_ok, upload_detail = check_upload_writable()
    thumb_ok, thumb_detail = check_thumb_cache_writable()
    secrets_ok, secret_issues = check_secrets()
    dist_ok, dist_detail = check_frontend_dist()

    checks = {
        "debug": settings.DEBUG,
        "storage_backend": getattr(settings, "STORAGE_BACKEND", "local"),
        "database": {"ok": db_ok, "detail": db_detail},
        "upload_writable": {"ok": upload_ok, "path": upload_detail},
        "thumb_cache_writable": {"ok": thumb_ok, "path": thumb_detail},
        "secrets": {"ok": secrets_ok, "issues": secret_issues},
        "frontend_dist": {"ok": dist_ok, "path": dist_detail},
    }
    checks["ready"] = (
        not settings.DEBUG
        and db_ok
        and upload_ok
        and thumb_ok
        and secrets_ok
        and dist_ok
    )
    return checks
