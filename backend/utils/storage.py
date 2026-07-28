"""Image upload storage backends — local filesystem or MinIO (S3-compatible)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from django.conf import settings

from utils.file_security import PathSecurityError, assert_safe_relative_path
from utils.path_builder import ensure_parent_dir, resolve_upload_file

logger = logging.getLogger(__name__)

_PROBE_KEY_SUFFIX = ".storage_probe"


@dataclass(frozen=True)
class StorageStat:
    size: int
    mtime: float


class ImageStorageBackend(Protocol):
    backend_name: str

    def exists(self, relative_path: str) -> bool: ...

    def read_bytes(self, relative_path: str) -> bytes: ...

    def write_bytes(self, relative_path: str, content: bytes) -> None: ...

    def delete(self, relative_path: str) -> tuple[bool, int]: ...

    def stat(self, relative_path: str) -> StorageStat | None: ...

    def check_writable(self) -> tuple[bool, str]: ...

    def estimate_disk_bytes(self) -> int | None: ...


class LocalImageStorage:
    backend_name = "local"

    def __init__(self, upload_root: str | Path):
        self.upload_root = Path(upload_root)

    def _abs_path(self, relative_path: str) -> Path:
        safe = assert_safe_relative_path(relative_path)
        return resolve_upload_file(self.upload_root, safe).resolve()

    def exists(self, relative_path: str) -> bool:
        try:
            return self._abs_path(relative_path).is_file()
        except (PathSecurityError, ValueError):
            return False

    def read_bytes(self, relative_path: str) -> bytes:
        path = self._abs_path(relative_path)
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        return path.read_bytes()

    def write_bytes(self, relative_path: str, content: bytes) -> None:
        path = ensure_parent_dir(self.upload_root, relative_path)
        path.write_bytes(content)

    def delete(self, relative_path: str) -> tuple[bool, int]:
        if not relative_path:
            return False, 0
        try:
            path = self._abs_path(relative_path)
            if not path.is_file():
                return False, 0
            size = path.stat().st_size
            path.unlink()
            return True, size
        except (PathSecurityError, ValueError) as exc:
            logger.warning("skip unsafe path during delete path=%s: %s", relative_path, exc)
            return False, 0
        except OSError:
            logger.warning("failed to delete file path=%s", relative_path, exc_info=True)
            return False, 0

    def stat(self, relative_path: str) -> StorageStat | None:
        try:
            path = self._abs_path(relative_path)
            if not path.is_file():
                return None
            st = path.stat()
            return StorageStat(size=st.st_size, mtime=st.st_mtime)
        except (PathSecurityError, ValueError, OSError):
            return None

    def get_local_path(self, relative_path: str) -> Path:
        """Return absolute path for FileResponse; raises if missing."""
        path = self._abs_path(relative_path)
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        return path

    def check_writable(self) -> tuple[bool, str]:
        root = self.upload_root.resolve()
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True, str(root)
        except Exception as exc:
            return False, str(exc)

    def estimate_disk_bytes(self) -> int | None:
        upload_dir = self.upload_root
        if upload_dir.name != "upload" and (upload_dir / "upload").is_dir():
            upload_dir = upload_dir / "upload"
        if not upload_dir.exists():
            return 0
        total = 0
        for item in upload_dir.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
        return total


class MinioImageStorage:
    backend_name = "minio"

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        prefix: str = "",
        secure: bool = False,
    ):
        from minio import Minio
        from minio.error import S3Error

        self._S3Error = S3Error
        host, port, use_ssl = _parse_minio_endpoint(endpoint, secure)
        self.client = Minio(
            f"{host}:{port}" if port else host,
            access_key=access_key,
            secret_key=secret_key,
            secure=use_ssl,
        )
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _object_key(self, relative_path: str) -> str:
        safe = assert_safe_relative_path(relative_path)
        if self.prefix:
            return f"{self.prefix}/{safe}"
        return safe

    def _probe_key(self) -> str:
        base = self.prefix or "image_db"
        return f"{base}/{_PROBE_KEY_SUFFIX}"

    def exists(self, relative_path: str) -> bool:
        key = self._object_key(relative_path)
        try:
            self.client.stat_object(self.bucket, key)
            return True
        except self._S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                return False
            raise

    def read_bytes(self, relative_path: str) -> bytes:
        key = self._object_key(relative_path)
        try:
            response = self.client.get_object(self.bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except self._S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                raise FileNotFoundError(relative_path) from exc
            raise

    def write_bytes(self, relative_path: str, content: bytes) -> None:
        key = self._object_key(relative_path)
        data = BytesIO(content)
        self.client.put_object(
            self.bucket,
            key,
            data,
            length=len(content),
            content_type="application/octet-stream",
        )

    def delete(self, relative_path: str) -> tuple[bool, int]:
        if not relative_path:
            return False, 0
        key = self._object_key(relative_path)
        size = 0
        try:
            stat = self.client.stat_object(self.bucket, key)
            size = stat.size
        except self._S3Error:
            return False, 0
        try:
            self.client.remove_object(self.bucket, key)
            return True, size
        except self._S3Error:
            logger.warning("failed to delete minio object key=%s", key, exc_info=True)
            return False, 0

    def stat(self, relative_path: str) -> StorageStat | None:
        key = self._object_key(relative_path)
        try:
            obj = self.client.stat_object(self.bucket, key)
            mtime = obj.last_modified.timestamp() if obj.last_modified else 0.0
            return StorageStat(size=obj.size, mtime=mtime)
        except self._S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                return None
            raise

    def check_writable(self) -> tuple[bool, str]:
        probe_key = self._probe_key()
        payload = b"ok"
        detail = f"minio://{self.bucket}/{self.prefix or ''}"
        try:
            self.client.put_object(
                self.bucket,
                probe_key,
                BytesIO(payload),
                length=len(payload),
            )
        except Exception as exc:
            return False, str(exc)
        try:
            self.client.remove_object(self.bucket, probe_key)
        except Exception as exc:
            # PutObject succeeded — storage is writable for uploads even if probe cleanup is denied.
            logger.warning(
                "minio probe write ok but cleanup failed bucket=%s key=%s: %s",
                self.bucket,
                probe_key,
                exc,
            )
        return True, detail

    def estimate_disk_bytes(self) -> int | None:
        return None


def _parse_minio_endpoint(endpoint: str, secure: bool) -> tuple[str, int | None, bool]:
    raw = (endpoint or "").strip()
    if not raw:
        raise ValueError("MINIO_ENDPOINT 未设置")

    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.hostname or ""
        port = parsed.port
        use_ssl = parsed.scheme == "https"
    else:
        host = raw
        port = None
        use_ssl = secure

    if not host:
        raise ValueError(f"MINIO_ENDPOINT 无效: {endpoint!r}")

    if port is None:
        port = 443 if use_ssl else 9000
    return host, port, use_ssl


_storage_instance: ImageStorageBackend | None = None
_storage_cached_key: tuple | None = None


def _build_storage_key() -> tuple:
    backend = getattr(settings, "STORAGE_BACKEND", "local").lower()
    if backend == "minio":
        return (
            backend,
            settings.MINIO_ENDPOINT,
            settings.MINIO_ACCESS_KEY,
            settings.MINIO_SECRET_KEY,
            settings.MINIO_BUCKET,
            settings.MINIO_PREFIX,
            settings.MINIO_SECURE,
        )
    return (backend, str(settings.UPLOAD_ROOT))


def get_image_storage() -> ImageStorageBackend:
    global _storage_instance, _storage_cached_key
    key = _build_storage_key()
    if _storage_instance is not None and _storage_cached_key == key:
        return _storage_instance

    backend = key[0]
    if backend == "minio":
        _storage_instance = MinioImageStorage(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            bucket=settings.MINIO_BUCKET,
            prefix=settings.MINIO_PREFIX,
            secure=settings.MINIO_SECURE,
        )
    else:
        _storage_instance = LocalImageStorage(settings.UPLOAD_ROOT)
    _storage_cached_key = key
    return _storage_instance


def reset_image_storage_cache() -> None:
    global _storage_instance, _storage_cached_key
    _storage_instance = None
    _storage_cached_key = None
