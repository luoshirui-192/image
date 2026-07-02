#!/usr/bin/env python3
"""Generate Django SECRET_KEY for production .env."""
from __future__ import annotations

from django.core.management.utils import get_random_secret_key


def main() -> int:
    print(get_random_secret_key())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
