"""Unified JSON API response helpers."""
from __future__ import annotations

from typing import Any

from rest_framework.response import Response


def success_response(data: Any = None, message: str = "success", code: int = 0, status: int = 200) -> Response:
    return Response({"code": code, "message": message, "data": data}, status=status)


def error_response(message: str, code: int = 1, data: Any = None, status: int = 400) -> Response:
    return Response({"code": code, "message": message, "data": data}, status=status)
