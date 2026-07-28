"""Operation audit log writer (reused by auth, SQL, upload modules)."""
from __future__ import annotations

import logging

from django.http import HttpRequest
from django.utils import timezone

from utils.request_helpers import get_client_ip

logger = logging.getLogger(__name__)


def write_operate_log(
    request: HttpRequest,
    action_type: str,
    *,
    detail: str = "",
    sql_content: str | None = None,
    username: str | None = None,
    user_id: int | None = None,
) -> None:
    from logs.models import OperateLog

    user = getattr(request, "user", None)
    if user_id is None and user and getattr(user, "is_authenticated", False):
        user_id = user.id
    if username is None and user and getattr(user, "is_authenticated", False):
        username = user.username

    try:
        OperateLog.objects.create(
            user_id=user_id,
            username=username or "",
            action_type=(action_type or "")[:20],
            sql_content=sql_content,
            detail=detail[:500],
            ip=get_client_ip(request),
            create_time=timezone.now(),
        )
    except Exception:
        logger.warning("Failed to write operate_log action=%s", action_type, exc_info=True)
