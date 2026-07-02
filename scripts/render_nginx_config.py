#!/usr/bin/env python3
"""
步骤 28 — 根据 deploy/paths.env 渲染 Nginx 站点配置。

用法：
  python scripts/render_nginx_config.py
  python scripts/render_nginx_config.py --paths deploy/paths.env
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "deploy/nginx/image_db.conf.template"
DEFAULT_PATHS = PROJECT_ROOT / "deploy/paths.env"
EXAMPLE_PATHS = PROJECT_ROOT / "deploy/paths.env.example"
OUTPUT = PROJECT_ROOT / "deploy/nginx/generated/image_db.conf"


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


def _to_nginx_path(path: str) -> str:
    """Normalize path for Nginx (forward slashes, no trailing slash on dirs used in root/alias)."""
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized


def render(paths_file: Path) -> str:
    if not paths_file.is_file():
        raise FileNotFoundError(
            f"未找到 {paths_file}，请先复制 deploy/paths.env.example 为 deploy/paths.env"
        )
    if not TEMPLATE.is_file():
        raise FileNotFoundError(f"缺少模板: {TEMPLATE}")

    cfg = _parse_env_file(paths_file)
    project = _to_nginx_path(cfg.get("PROJECT_ROOT", str(PROJECT_ROOT)))
    frontend_dist = f"{project}/frontend/dist"
    upload_root = _to_nginx_path(cfg.get("UPLOAD_ROOT", f"{project}/upload"))

    enable_upload = cfg.get("ENABLE_UPLOAD_DIRECT", "0").lower() in ("1", "true", "yes", "on")
    upload_location = ""
    if enable_upload:
        upload_location = f"""    # 直出上传目录（ENABLE_UPLOAD_DIRECT=1；会绕过 JWT，仅建议内网）
    location /upload/ {{
        alias {upload_root}/;
        autoindex off;
        expires 1d;
    }}
"""

    text = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "{{BACKEND_UPSTREAM}}": cfg.get("BACKEND_UPSTREAM", "127.0.0.1:8000"),
        "{{LISTEN_PORT}}": cfg.get("LISTEN_PORT", "80"),
        "{{SERVER_NAME}}": cfg.get("SERVER_NAME", "localhost"),
        "{{CLIENT_MAX_BODY_SIZE}}": cfg.get("CLIENT_MAX_BODY_SIZE", "25m"),
        "{{FRONTEND_DIST}}": frontend_dist,
        "{{UPLOAD_LOCATION}}": upload_location.rstrip("\n"),
    }
    for key, value in replacements.items():
        text = text.replace(key, value)

    if "{{" in text:
        missing = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", text)))
        raise ValueError(f"模板仍有未替换占位符: {', '.join(missing)}")

    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染 Nginx image_db 站点配置")
    parser.add_argument(
        "--paths",
        type=Path,
        default=DEFAULT_PATHS,
        help="paths.env 路径（默认 deploy/paths.env）",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="输出到标准输出，不写文件",
    )
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
    print("下一步: 复制到服务器 /etc/nginx/sites-available/ 并 nginx -t")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
