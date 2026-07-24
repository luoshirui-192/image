"""Store and resolve external MySQL connections configured from the Web UI."""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.db import connections
from django.utils import timezone

from images.models import ExternalDbConnection

logger = logging.getLogger(__name__)

EXTERNAL_ALIAS_PREFIX = "external_"
SESSION_ALIAS_PREFIX = "session_"
PASSWORD_KEY_SALT = "external-db-password-v1"
HOST_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
PORT_MIN = 1
PORT_MAX = 65535
CONNECT_TIMEOUT = 10
_SESSION_ALIAS_LOCK = threading.Lock()


def _running_in_docker() -> bool:
    return Path("/.dockerenv").exists()


def normalize_host(host: str) -> str:
    """Normalize host input; map localhost to host.docker.internal inside Docker."""
    value = (host or "").strip()
    if value.lower().startswith("mysql://"):
        value = value[7:]
    if "@" in value:
        value = value.rsplit("@", 1)[-1]
    if "/" in value:
        value = value.split("/", 1)[0]
    if ":" in value and not value.startswith("["):
        value = value.rsplit(":", 1)[0]
    value = value.strip()
    if value.lower() in {"localhost", "127.0.0.1", "::1"} and _running_in_docker():
        return "host.docker.internal"
    return value


class ExternalDbError(Exception):
    pass


def external_alias(connection_id: int) -> str:
    return f"{EXTERNAL_ALIAS_PREFIX}{connection_id}"


def parse_external_alias(alias: str) -> int | None:
    if not alias or not alias.startswith(EXTERNAL_ALIAS_PREFIX):
        return None
    suffix = alias[len(EXTERNAL_ALIAS_PREFIX) :]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _password_key() -> bytes:
    material = f"{PASSWORD_KEY_SALT}::{settings.SECRET_KEY}".encode("utf-8")
    return hashlib.sha256(material).digest()


def encrypt_password(password: str) -> str:
    key = _password_key()
    raw = (password or "").encode("utf-8")
    encrypted = bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))
    return base64.urlsafe_b64encode(encrypted).decode("ascii")


def decrypt_password(token: str) -> str:
    if not token:
        return ""
    try:
        key = _password_key()
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        decrypted = bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))
        return decrypted.decode("utf-8")
    except Exception as exc:
        raise ExternalDbError("无法解密数据库密码，请重新保存连接") from exc


def _mysql_options(charset: str) -> dict:
    from django.conf import settings as django_settings

    db_charset = charset or "utf8"
    mysql51_compat = getattr(django_settings, "MYSQL51_COMPAT", False)
    if not mysql51_compat:
        import os

        mysql51_compat = os.getenv("MYSQL51_COMPAT", "false").lower() in {"1", "true", "yes", "on"}
    if mysql51_compat and db_charset in ("utf8", "utf8mb3", "utf8mb4"):
        return {
            "charset": "latin1",
            "init_command": "SET NAMES utf8; SET time_zone = '+08:00'",
        }
    wire_charset = "utf8mb4" if db_charset == "utf8mb4" else "utf8"
    return {
        "charset": wire_charset,
        "init_command": f"SET NAMES {db_charset}; SET time_zone = '+08:00'",
    }


def _connect_mysql_direct(
    *,
    host: str,
    port: int,
    db_name: str,
    username: str,
    password: str,
    charset: str = "utf8",
) -> None:
    """Lightweight connectivity check with clearer errors than Django DB wrapper."""
    import MySQLdb

    wire_charset = "utf8mb4" if charset == "utf8mb4" else "utf8"
    try:
        conn = MySQLdb.connect(
            host=host,
            port=int(port),
            user=username,
            passwd=password,
            db=db_name,
            charset=wire_charset,
            connect_timeout=CONNECT_TIMEOUT,
        )
    except MySQLdb.OperationalError as exc:
        raise ExternalDbError(_format_mysql_error(exc, host=host, port=port)) from exc
    except Exception as exc:
        raise ExternalDbError(f"连接失败: {exc}") from exc

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    finally:
        conn.close()


def _format_mysql_error(exc: Exception, *, host: str, port: int) -> str:
    message = str(exc).strip()
    lower = message.lower()
    if "can't connect" in lower or "timed out" in lower or "connection refused" in lower:
        hint = (
            f"无法连接 {host}:{port}。"
            "若旧库在本机，Docker 部署请填 host.docker.internal 或宿主机局域网 IP，"
            "不要填 127.0.0.1/localhost。"
        )
        return f"{message}。{hint}"
    if "access denied" in lower:
        return f"{message}。请检查用户名、密码，以及 MySQL 是否允许该账号从 Docker 容器 IP 远程登录。"
    if "unknown database" in lower:
        return f"{message}。请确认数据库名是否正确。"
    return message


def build_database_settings(record: ExternalDbConnection, *, password: str | None = None, database: str | None = None) -> dict:
    pwd = password if password is not None else decrypt_password(record.password_encrypted)
    db_name = (database or record.db_name or "").strip() or record.db_name
    return {
        "ENGINE": "config.db_backend",
        "NAME": db_name,
        "USER": record.username,
        "PASSWORD": pwd,
        "HOST": record.host,
        "PORT": str(record.port),
        "OPTIONS": _mysql_options(record.charset),
        "TIME_ZONE": settings.TIME_ZONE,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "AUTOCOMMIT": True,
        "ATOMIC_REQUESTS": False,
    }


def validate_connection_fields(
    *,
    name: str,
    host: str,
    port,
    db_name: str,
    username: str,
    password: str | None = None,
    require_password: bool = True,
) -> dict:
    clean_name = (name or "").strip()
    clean_host = normalize_host(host)
    clean_db = (db_name or "").strip()
    clean_user = (username or "").strip()
    if not clean_name:
        raise ExternalDbError("连接名称不能为空")
    if not clean_host or not HOST_RE.match(clean_host):
        raise ExternalDbError(
            f"主机地址无效: {host!r}。"
            "请填写 IP 或域名，不要带 http:// 或 :3306。"
            "Docker 内访问本机 MySQL 请用 host.docker.internal。"
        )
    try:
        clean_port = int(port)
    except (TypeError, ValueError) as exc:
        raise ExternalDbError("端口无效") from exc
    if not PORT_MIN <= clean_port <= PORT_MAX:
        raise ExternalDbError("端口无效")
    if not clean_db:
        raise ExternalDbError("数据库名不能为空")
    if not clean_user:
        raise ExternalDbError("用户名不能为空")
    if require_password and not (password or "").strip():
        raise ExternalDbError("密码不能为空")
    return {
        "name": clean_name[:100],
        "host": clean_host[:255],
        "port": clean_port,
        "db_name": clean_db[:64],
        "username": clean_user[:100],
    }


def test_connection_settings(settings_dict: dict) -> str:
    charset = "utf8"
    options = settings_dict.get("OPTIONS") or {}
    init_cmd = options.get("init_command") or ""
    if "utf8mb4" in init_cmd:
        charset = "utf8mb4"
    _connect_mysql_direct(
        host=normalize_host(settings_dict["HOST"]),
        port=int(settings_dict["PORT"]),
        db_name=settings_dict["NAME"],
        username=settings_dict["USER"],
        password=settings_dict["PASSWORD"],
        charset=charset,
    )
    return "连接成功"


def register_external_connection(connection_id: int, *, database: str | None = None) -> str:
    alias = external_alias(connection_id)
    try:
        record = ExternalDbConnection.objects.get(pk=connection_id, enabled=1)
    except ExternalDbConnection.DoesNotExist as exc:
        raise ExternalDbError(f"外部库连接不存在或已禁用: id={connection_id}") from exc

    connections.databases[alias] = build_database_settings(record, database=database)
    connections[alias].ensure_connection()
    return alias


def unregister_external_connection(connection_id: int) -> None:
    alias = external_alias(connection_id)
    if alias in connections.databases:
        try:
            connections[alias].close()
        except Exception:
            logger.warning("close external connection failed alias=%s", alias, exc_info=True)
        connections.databases.pop(alias, None)


def _alloc_session_alias(settings_dict: dict) -> str:
    """Register an ephemeral DB alias. Never mutates default/legacy/external_* entries."""
    with _SESSION_ALIAS_LOCK:
        session_alias = f"{SESSION_ALIAS_PREFIX}{uuid.uuid4().hex}"
        connections.databases[session_alias] = settings_dict
    return session_alias


def _cleanup_session_alias(session_alias: str) -> None:
    try:
        connections[session_alias].close()
    except Exception:
        logger.warning("close session alias failed alias=%s", session_alias, exc_info=True)
    with _SESSION_ALIAS_LOCK:
        connections.databases.pop(session_alias, None)


@contextmanager
def open_external_connection(connection_id: int, *, database: str | None = None):
    alias = register_external_connection(connection_id, database=database)
    try:
        yield alias
    finally:
        unregister_external_connection(connection_id)


def validate_db_alias_reference(alias: str) -> str:
    """Validate alias without opening a connection."""
    value = (alias or "default").strip() or "default"
    ext_id = parse_external_alias(value)
    if ext_id is not None:
        if not ExternalDbConnection.objects.filter(pk=ext_id, enabled=1).exists():
            raise ExternalDbError(f"外部库连接不存在或已禁用: {value}")
        return value
    if value not in connections:
        raise ExternalDbError(f"数据库别名不存在: {value}")
    return value


@contextmanager
def db_alias_session(alias: str, *, database: str | None = None):
    """
    Yield a usable DB alias for the duration of a catalog/SQL/migration operation.

    Critical: never mutate process-global ``default`` / ``legacy`` NAME in place.
    Concurrent SQL sessions that switched databases used to permanently leave
    ``default`` pointing at the wrong schema, breaking image serve and migration stats.
    """
    value = validate_db_alias_reference(alias)
    ext_id = parse_external_alias(value)
    db_name = (database or "").strip() or None

    if ext_id is not None:
        try:
            record = ExternalDbConnection.objects.get(pk=ext_id, enabled=1)
        except ExternalDbConnection.DoesNotExist as exc:
            raise ExternalDbError(f"外部库连接不存在或已禁用: id={ext_id}") from exc
        settings_dict = build_database_settings(record, database=db_name)
        session_alias = _alloc_session_alias(settings_dict)
        try:
            connections[session_alias].ensure_connection()
            yield session_alias
        finally:
            _cleanup_session_alias(session_alias)
        return

    base = connections.databases.get(value)
    if base is None:
        raise ExternalDbError(f"数据库别名不存在: {value}")
    current_name = str(base.get("NAME") or "")
    if not db_name or db_name == current_name:
        yield value
        return

    # Clone onto an ephemeral alias — do not patch default/legacy.
    patched = dict(base)
    patched["NAME"] = db_name
    session_alias = _alloc_session_alias(patched)
    try:
        connections[session_alias].ensure_connection()
        yield session_alias
    finally:
        _cleanup_session_alias(session_alias)


def resolve_db_alias(alias: str) -> str:
    """Ensure alias is usable and return normalized alias."""
    value = (alias or "default").strip() or "default"
    ext_id = parse_external_alias(value)
    if ext_id is not None:
        return register_external_connection(ext_id)
    if value not in connections:
        raise ExternalDbError(f"数据库别名不存在: {value}")
    return value


def list_database_aliases() -> list[dict]:
    items: list[dict] = []
    if "default" in connections:
        cfg = connections["default"].settings_dict
        items.append(
            {
                "alias": "default",
                "type": "system",
                "label": "本系统库",
                "name": cfg.get("NAME", ""),
                "host": cfg.get("HOST", ""),
                "port": cfg.get("PORT", ""),
            }
        )
    if "legacy" in connections:
        cfg = connections["legacy"].settings_dict
        items.append(
            {
                "alias": "legacy",
                "type": "env",
                "label": "环境变量旧库 (LEGACY_DB_*)",
                "name": cfg.get("NAME", ""),
                "host": cfg.get("HOST", ""),
                "port": cfg.get("PORT", ""),
            }
        )

    for record in ExternalDbConnection.objects.filter(enabled=1).order_by("id"):
        items.append(
            {
                "alias": external_alias(record.id),
                "type": "external",
                "label": record.name,
                "name": record.db_name,
                "host": record.host,
                "port": record.port,
                "connection_id": record.id,
                "last_test_ok": record.last_test_ok,
                "last_test_at": record.last_test_at.isoformat() if record.last_test_at else None,
            }
        )
    return items


def serialize_connection(record: ExternalDbConnection) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "host": record.host,
        "port": record.port,
        "db_name": record.db_name,
        "username": record.username,
        "charset": record.charset,
        "remark": record.remark,
        "enabled": record.enabled,
        "alias": external_alias(record.id),
        "has_password": bool(record.password_encrypted),
        "last_test_at": record.last_test_at,
        "last_test_ok": record.last_test_ok,
        "last_test_message": record.last_test_message,
        "create_time": record.create_time,
        "update_time": record.update_time,
    }


def create_external_connection(**fields) -> ExternalDbConnection:
    validated = validate_connection_fields(
        name=fields.get("name", ""),
        host=fields.get("host", ""),
        port=fields.get("port", 3306),
        db_name=fields.get("db_name", ""),
        username=fields.get("username", ""),
        password=fields.get("password"),
        require_password=True,
    )
    now = timezone.now()
    record = ExternalDbConnection(
        **validated,
        password_encrypted=encrypt_password(fields["password"]),
        charset=(fields.get("charset") or "utf8")[:16],
        remark=(fields.get("remark") or "")[:500],
        enabled=1,
        create_time=now,
        update_time=now,
    )
    record.save(force_insert=True)
    return record


def update_external_connection(record: ExternalDbConnection, **fields) -> ExternalDbConnection:
    validated = validate_connection_fields(
        name=fields.get("name", record.name),
        host=fields.get("host", record.host),
        port=fields.get("port", record.port),
        db_name=fields.get("db_name", record.db_name),
        username=fields.get("username", record.username),
        password=fields.get("password"),
        require_password=False,
    )
    record.name = validated["name"]
    record.host = validated["host"]
    record.port = validated["port"]
    record.db_name = validated["db_name"]
    record.username = validated["username"]
    if fields.get("charset") is not None:
        record.charset = (fields["charset"] or "utf8")[:16]
    if fields.get("remark") is not None:
        record.remark = (fields["remark"] or "")[:500]
    if fields.get("enabled") is not None:
        record.enabled = 1 if fields["enabled"] else 0
    password = fields.get("password")
    if password:
        record.password_encrypted = encrypt_password(password)
    record.update_time = timezone.now()
    record.save()
    unregister_external_connection(record.id)
    return record


def test_external_connection(record: ExternalDbConnection, *, password: str | None = None) -> str:
    pwd = password if password else decrypt_password(record.password_encrypted)
    _connect_mysql_direct(
        host=normalize_host(record.host),
        port=record.port,
        db_name=record.db_name,
        username=record.username,
        password=pwd,
        charset=record.charset,
    )
    message = "连接成功"
    record.last_test_at = timezone.now()
    record.last_test_ok = 1
    record.last_test_message = message[:500]
    record.update_time = timezone.now()
    record.save(
        update_fields=["last_test_at", "last_test_ok", "last_test_message", "update_time"]
    )
    return message


def test_connection_payload(**fields) -> str:
    validated = validate_connection_fields(
        name=fields.get("name") or "test",
        host=fields.get("host", ""),
        port=fields.get("port", 3306),
        db_name=fields.get("db_name", ""),
        username=fields.get("username", ""),
        password=fields.get("password"),
        require_password=True,
    )
    _connect_mysql_direct(
        host=validated["host"],
        port=validated["port"],
        db_name=validated["db_name"],
        username=validated["username"],
        password=fields["password"],
        charset=fields.get("charset") or "utf8",
    )
    return "连接成功"
