#!/usr/bin/env python3
"""
步骤 29 — 根据 deploy/paths.env 渲染 systemd 单元文件。

用法：
  python scripts/render_gunicorn_service.py
  python scripts/render_gunicorn_service.py --paths deploy/paths.env
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "deploy/gunicorn/image_db.service.template"
DEFAULT_PATHS = PROJECT_ROOT / "deploy/paths.env"
EXAMPLE_PATHS = PROJECT_ROOT / "deploy/paths.env.example"
OUTPUT = PROJECT_ROOT / "deploy/gunicorn/generated/image_db.service"


def _parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip()
    return data


def _to_unix_path(path: str) -> str:
    return path.replace("\\", "/").rstrip("/")


def render(paths_file: Path) -> str:
    if not paths_file.is_file():
        raise FileNotFoundError(
            f"未找到 {paths_file}，请先复制 deploy/paths.env.example 为 deploy/paths.env"
        )
    if not TEMPLATE.is_file():
        raise FileNotFoundError(f"缺少模板: {TEMPLATE}")

    cfg = _parse_env_file(paths_file)
    project = _to_unix_path(cfg.get("PROJECT_ROOT", str(PROJECT_ROOT)))
    venv_path = _to_unix_path(cfg.get("VENV_PATH", f"{project}/.venv"))
    venv_bin = f"{venv_path}/bin"

    gunicorn_bind = cfg.get("GUNICORN_BIND") or cfg.get("BACKEND_UPSTREAM", "127.0.0.1:8000")
    gunicorn_workers = cfg.get("GUNICORN_WORKERS", "3")
    gunicorn_timeout = cfg.get("GUNICORN_TIMEOUT", "120")

    text = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "{{PROJECT_ROOT}}": project,
        "{{VENV_BIN}}": venv_bin,
        "{{RUN_USER}}": cfg.get("RUN_USER", "www-data"),
        "{{RUN_GROUP}}": cfg.get("RUN_GROUP", "www-data"),
        "{{GUNICORN_BIND}}": gunicorn_bind,
        "{{GUNICORN_WORKERS}}": gunicorn_workers,
        "{{GUNICORN_TIMEOUT}}": gunicorn_timeout,
    }
    for key, value in replacements.items():
        text = text.replace(key, value)

    if "{{" in text:
        missing = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", text)))
        raise ValueError(f"模板仍有未替换占位符: {', '.join(missing)}")

    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染 Gunicorn systemd 单元")
    parser.add_argument("--paths", type=Path, default=DEFAULT_PATHS)
    parser.add_argument("--stdout", action="store_true", help="输出到标准输出")
    args = parser.parse_args()

    paths_file = args.paths
    if not paths_file.is_file() and paths_file == DEFAULT_PATHS and EXAMPLE_PATHS.is_file():
        print(f"[INFO] 未找到 deploy/paths.env，使用 {EXAMPLE_PATHS.name} 示例值")
        paths_file = EXAMPLE_PATHS

    content = render(paths_file)

    if args.stdout:
        print(content, end="")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"已生成: {OUTPUT}")
    print("下一步:")
    print("  sudo cp deploy/gunicorn/generated/image_db.service /etc/systemd/system/")
    print("  sudo systemctl daemon-reload && sudo systemctl enable --now image_db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
