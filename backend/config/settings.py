"""
Django settings for 图像路径式数据库管理系统 backend.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(BASE_DIR / ".env", override=True)  # .env 优先于终端里残留的 DB_ENGINE=sqlite

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-key-change-in-production")
DEBUG = os.getenv("DEBUG", "True").lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
    if h.strip()
]

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",
    "users",
    "images",
    "sqlquery",
    "logs",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_ENGINE = os.getenv("DB_ENGINE", "mysql").lower()
RUNNING_TESTS = "test" in sys.argv

if DB_ENGINE == "sqlite" or RUNNING_TESTS:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    # MySQL 5.1.x: no utf8mb4/utf8mb3. mysqlclient 2.2+ maps utf8→utf8mb3.
    # Workaround: handshake charset latin1, session charset via SET NAMES utf8.
    db_charset = os.getenv("DB_CHARSET", "utf8")
    if db_charset in ("utf8", "utf8mb3", "utf8mb4"):
        db_options: dict = {
            "charset": "latin1",
            "init_command": "SET NAMES utf8; SET time_zone = '+08:00'",
        }
    else:
        db_options = {
            "charset": db_charset,
            "init_command": f"SET NAMES {db_charset}",
        }

    DATABASES = {
        "default": {
            "ENGINE": "config.db_backend",
            "NAME": os.getenv("DB_NAME", "image_db"),
            "USER": os.getenv("DB_USER", "root"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "127.0.0.1"),
            "PORT": os.getenv("DB_PORT", "3306"),
            "OPTIONS": db_options,
        }
    }

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "users.SysUser"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

# ---------------------------------------------------------------------------
# i18n / time
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static / media
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Project paths (Step 8)
# ---------------------------------------------------------------------------

UPLOAD_ROOT = os.getenv("UPLOAD_ROOT", str(PROJECT_ROOT / "upload"))
IMPORT_SCAN_ROOT = os.getenv("IMPORT_SCAN_ROOT", str(PROJECT_ROOT))
THUMB_CACHE_ROOT = os.getenv("THUMB_CACHE_ROOT", str(BASE_DIR / "thumb_cache"))
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
THUMB_SIZE = int(os.getenv("THUMB_SIZE", "200"))

IMAGE_ACCESS_SECRET = os.getenv("IMAGE_ACCESS_SECRET", SECRET_KEY)
IMAGE_ACCESS_TOKEN_TTL = int(os.getenv("IMAGE_ACCESS_TOKEN_TTL", "3600"))

# SQL query limits (Step 13)
SQL_QUERY_TIMEOUT = int(os.getenv("SQL_QUERY_TIMEOUT", "10"))
SQL_MAX_ROWS = int(os.getenv("SQL_MAX_ROWS", "1000"))
SQL_REQUIRE_WHERE_FOR_SELECT_STAR = os.getenv("SQL_REQUIRE_WHERE_FOR_SELECT_STAR", "False").lower() in {
    "1", "true", "yes", "on",
}

# Maintenance (Step 16)
DELETED_IMAGE_RETENTION_DAYS = int(os.getenv("DELETED_IMAGE_RETENTION_DAYS", "30"))
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "90"))

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
]
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

# ---------------------------------------------------------------------------
# Production hardening (DEBUG=False)
# ---------------------------------------------------------------------------

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SESSION_COOKIE_HTTPONLY = True

    proxy_ssl = os.getenv("SECURE_PROXY_SSL_HEADER", "").strip()
    if proxy_ssl and "," in proxy_ssl:
        header, value = proxy_ssl.split(",", 1)
        SECURE_PROXY_SSL_HEADER = (header.strip(), value.strip())
        SESSION_COOKIE_SECURE = True
        CSRF_COOKIE_SECURE = True

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

if not DEBUG:
    LOG_DIR = BASE_DIR / "logs"
    LOG_DIR.mkdir(exist_ok=True)
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "verbose": {
                "format": "{asctime} {levelname} {name} {message}",
                "style": "{",
            },
        },
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(LOG_DIR / "django.log"),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 3,
                "formatter": "verbose",
                "encoding": "utf-8",
            },
        },
        "root": {
            "handlers": ["console", "file"],
            "level": os.getenv("LOG_LEVEL", "INFO"),
        },
    }
else:
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "console": {"class": "logging.StreamHandler"},
        },
        "root": {
            "handlers": ["console"],
            "level": "INFO",
        },
    }

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "utils.exceptions.custom_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("JWT_ACCESS_MINUTES", "120"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("JWT_REFRESH_DAYS", "7"))),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "图像路径式数据库管理系统 API",
    "DESCRIPTION": "图片元数据 + 路径存储 + SQL 查询面板",
    "VERSION": "1.0.0",
}
