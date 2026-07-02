#!/usr/bin/env python3
"""
步骤 27 — 生产环境验收

检查 DEBUG、数据库、存储目录、密钥、前端 dist 等。

用法：
  python scripts/verify_production.py
  python scripts/verify_production.py --url http://127.0.0.1:8000/api/health/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from config.readiness import collect_readiness  # noqa: E402


def verify_local() -> bool:
    data = collect_readiness()
    print("=== 本地就绪检查 ===")
    print(json.dumps(data, ensure_ascii=False, indent=2))

    ok = True
    if data.get("debug"):
        print("\n[WARN] DEBUG=True，生产环境请设 DEBUG=False")
        ok = False
    if not data.get("database", {}).get("ok"):
        print("\n[FAIL] 数据库不可用")
        ok = False
    if not data.get("upload_writable", {}).get("ok"):
        print("\n[FAIL] upload 目录不可写")
        ok = False
    if not data.get("secrets", {}).get("ok"):
        print("\n[FAIL] 密钥未更换:", data.get("secrets", {}).get("issues"))
        ok = False
    if not data.get("frontend_dist", {}).get("ok"):
        print("\n[FAIL] 未找到 frontend/dist，请运行 npm run build")
        ok = False
    if data.get("ready"):
        print("\n[PASS] readiness.ready = true")
    else:
        print("\n[WARN] readiness.ready = false（见上方明细）")
        ok = False
    return ok


def verify_http(url: str) -> bool:
    print(f"\n=== HTTP 检查 {url} ===")
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print(f"[FAIL] 无法访问: {exc}")
        return False

    print(json.dumps(body, ensure_ascii=False, indent=2))
    if body.get("code") != 0:
        print("[FAIL] health code != 0")
        return False
    readiness = body.get("data", {}).get("readiness", {})
    if readiness.get("ready"):
        print("[PASS] API health readiness.ready = true")
        return True
    print("[WARN] API 返回但 readiness 未全部通过")
    return False


def verify_nginx(base_url: str) -> bool:
    """步骤 28：经 Nginx 检查 SPA 首页与 /api/health/ 反代。"""
    base = base_url.rstrip("/")
    ok = True

    print(f"\n=== Nginx 检查 {base} ===")
    index_url = f"{base}/"
    try:
        with urllib.request.urlopen(index_url, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            ctype = resp.headers.get("Content-Type", "")
    except urllib.error.URLError as exc:
        print(f"[FAIL] 无法访问首页 {index_url}: {exc}")
        return False

    if "text/html" not in ctype:
        print(f"[WARN] 首页 Content-Type 非 HTML: {ctype}")
        ok = False
    if 'id="app"' not in html and "<div id=\"app\">" not in html:
        print("[FAIL] 首页未包含 Vue 挂载点 #app")
        ok = False
    else:
        print("[PASS] 首页返回 SPA index.html")

    health_url = f"{base}/api/health/"
    try:
        with urllib.request.urlopen(health_url, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print(f"[FAIL] 无法访问 {health_url}: {exc}")
        return False

    if body.get("code") != 0:
        print("[FAIL] /api/health/ code != 0")
        ok = False
    else:
        print("[PASS] /api/health/ 反代正常")

    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="",
        help="对已启动后端的 health URL，例如 http://127.0.0.1:8000/api/health/",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="仅本地检查，不要求 production ready（开发环境用）",
    )
    parser.add_argument(
        "--nginx-base",
        default="",
        help="步骤 28：Nginx 对外根地址，例如 http://192.168.1.100",
    )
    args = parser.parse_args()

    if args.local_only:
        data = collect_readiness()
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    local_ok = verify_local()
    http_ok = True
    nginx_ok = True
    if args.url:
        http_ok = verify_http(args.url)
    if args.nginx_base:
        nginx_ok = verify_nginx(args.nginx_base)

    if local_ok and http_ok and nginx_ok:
        print("\n验收通过")
        return 0
    print("\n验收未完全通过，请按 docs/deploy.md 排查")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
