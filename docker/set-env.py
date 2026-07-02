#!/usr/bin/env python3
"""根据 .env 中的 PUBLIC_URL 同步 ALLOWED_HOSTS / CORS_ALLOWED_ORIGINS。"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def _upsert(lines: list[str], key: str, value: str) -> list[str]:
    pattern = re.compile(rf"^{re.escape(key)}=")
    out = [line for line in lines if not pattern.match(line.strip())]
    out.append(f"{key}={value}")
    return out


def main() -> int:
    if not ENV_FILE.is_file():
        print(f"未找到 {ENV_FILE}，请先复制 .env.docker.example 为 .env")
        return 1

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    data = {}
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            data[k.strip()] = v.strip()

    public = data.get("PUBLIC_URL", "http://localhost").rstrip("/")
    parsed = urlparse(public)
    host = parsed.hostname or "localhost"
    allowed = f"localhost,127.0.0.1,backend,{host}"
    lines = _upsert(lines, "ALLOWED_HOSTS", allowed)
    lines = _upsert(lines, "CORS_ALLOWED_ORIGINS", public)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"PUBLIC_URL={public}")
    print(f"ALLOWED_HOSTS={allowed}")
    print(f"CORS_ALLOWED_ORIGINS={public}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
