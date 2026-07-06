"""Operate log filtering and pagination — Step 16."""
from __future__ import annotations

from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils.dateparse import parse_datetime

from logs.models import OperateLog


def _parse_datetime(value: str | None):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"无效的时间格式: {value}")
    return parsed


def filter_operate_log_queryset(request: HttpRequest) -> QuerySet:
    qs = OperateLog.objects.all()

    username = request.query_params.get("username", "").strip()
    if username:
        qs = qs.filter(username__icontains=username)

    action_type = request.query_params.get("action_type", "").strip()
    if action_type:
        qs = qs.filter(action_type=action_type)

    keyword = (request.query_params.get("keyword") or request.query_params.get("q") or "").strip()
    if keyword:
        qs = qs.filter(
            Q(detail__icontains=keyword)
            | Q(sql_content__icontains=keyword)
            | Q(username__icontains=keyword)
            | Q(ip__icontains=keyword)
        )

    user_id = request.query_params.get("user_id")
    if user_id not in (None, ""):
        try:
            parsed_user_id = int(user_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("user_id 必须为整数") from exc
        qs = qs.filter(user_id=parsed_user_id)

    time_from = _parse_datetime(request.query_params.get("create_time_from"))
    time_to = _parse_datetime(request.query_params.get("create_time_to"))
    if time_from:
        qs = qs.filter(create_time__gte=time_from)
    if time_to:
        qs = qs.filter(create_time__lte=time_to)

    return qs.order_by("-create_time", "-id")


def paginate_logs(request: HttpRequest, queryset: QuerySet, *, default_page_size: int = 20, max_page_size: int = 100) -> dict:
    try:
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", default_page_size))
    except (TypeError, ValueError) as exc:
        raise ValueError("page 和 page_size 必须为整数") from exc

    if page < 1:
        raise ValueError("page 必须 >= 1")
    if page_size < 1:
        raise ValueError("page_size 必须 >= 1")

    page_size = min(page_size, max_page_size)
    total = queryset.count()
    start = (page - 1) * page_size
    items = list(queryset[start : start + page_size])

    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "results": items,
    }
