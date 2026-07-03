#!/usr/bin/env python3
"""
步骤 30 — 生产冒烟测试（HTTP 端到端）。

验证健康检查、登录、核心只读 API；可选经 Nginx 全链路。

用法：
  python scripts/smoke_test.py --base-url http://127.0.0.1:8000
  python scripts/smoke_test.py --base-url http://192.168.1.100
  python scripts/smoke_test.py --base-url http://127.0.0.1:8000 --username admin --password admin123
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""


def _join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _request(
    method: str,
    url: str,
    *,
    data: dict | None = None,
    token: str | None = None,
    timeout: float = 15,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
        return resp.status, payload


def step_health(base: str, _token: str | None) -> StepResult:
    url = _join_url(base, "/api/health/")
    try:
        status, body = _request("GET", url)
    except urllib.error.URLError as exc:
        return StepResult("health", False, str(exc))
    if status != 200 or body.get("code") != 0:
        return StepResult("health", False, f"status={status} body={body}")
    readiness = body.get("data", {}).get("readiness", {})
    detail = f"ready={readiness.get('ready')}"
    return StepResult("health", True, detail)


def step_login(base: str, creds: dict[str, str]) -> tuple[StepResult, str | None]:
    url = _join_url(base, "/api/auth/login/")
    try:
        status, body = _request("POST", url, data=creds)
    except urllib.error.URLError as exc:
        return StepResult("login", False, str(exc)), None
    if status != 200 or body.get("code") != 0:
        return StepResult("login", False, body.get("message", str(body))), None
    token = body.get("data", {}).get("access")
    if not token:
        return StepResult("login", False, "响应缺少 access token"), None
    user = body.get("data", {}).get("user", {})
    return StepResult("login", True, f"user={user.get('username')} role={user.get('role')}"), token


def step_authed_get(name: str, base: str, path: str, token: str) -> StepResult:
    url = _join_url(base, path)
    try:
        status, body = _request("GET", url, token=token)
    except urllib.error.URLError as exc:
        return StepResult(name, False, str(exc))
    if status != 200 or body.get("code") != 0:
        return StepResult(name, False, body.get("message", str(body)))
    return StepResult(name, True, "ok")


def run_smoke(
    base_url: str,
    username: str,
    password: str,
) -> list[StepResult]:
    results: list[StepResult] = []

    health = step_health(base_url, None)
    results.append(health)
    if not health.ok:
        return results

    login_step, token = step_login(base_url, {"username": username, "password": password})
    results.append(login_step)
    if not login_step.ok or not token:
        return results

    authed_steps: list[tuple[str, str]] = [
        ("auth_me", "/api/auth/me/"),
        ("categories", "/api/images/categories/"),
        ("system_config", "/api/config/"),
        ("logs_stats", "/api/logs/stats/"),
    ]
    for name, path in authed_steps:
        results.append(step_authed_get(name, base_url, path, token))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="生产冒烟测试")
    parser.add_argument(
        "--base-url",
        required=True,
        help="API 根地址，如 http://127.0.0.1:8000 或 http://192.168.1.100（经 Nginx）",
    )
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    args = parser.parse_args()

    print(f"=== 冒烟测试 {args.base_url} ===")
    results = run_smoke(args.base_url, args.username, args.password)

    failed = 0
    for item in results:
        mark = "PASS" if item.ok else "FAIL"
        suffix = f" — {item.detail}" if item.detail else ""
        print(f"[{mark}] {item.name}{suffix}")
        if not item.ok:
            failed += 1

    if failed:
        print(f"\n{failed} 项失败")
        return 1
    print(f"\n全部 {len(results)} 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
