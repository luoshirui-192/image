"""Operation log API."""
from __future__ import annotations

from django.db.models import Q
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from images.maintenance import compute_storage_stats
from logs.models import OperateLog
from logs.serializers import OperateLogSerializer
from utils.permissions import IsActiveAccount, IsAdminRole
from utils.responses import success_response


class OperateLogPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _parse_datetime_param(value: str | None):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        parsed = parse_datetime(f"{value}T00:00:00")
    return parsed


@extend_schema(tags=["logs"])
class OperateLogListView(APIView):
    """GET /api/logs/ — paginated operation logs (admin only)."""

    permission_classes = [IsAuthenticated, IsActiveAccount, IsAdminRole]

    def get(self, request):
        qs = OperateLog.objects.all().order_by("-create_time", "-id")

        username = (request.query_params.get("username") or "").strip()
        if username:
            qs = qs.filter(username__icontains=username)

        action_type = (request.query_params.get("action_type") or "").strip()
        if action_type:
            qs = qs.filter(action_type=action_type)

        keyword = (request.query_params.get("keyword") or "").strip()
        if keyword:
            qs = qs.filter(
                Q(detail__icontains=keyword)
                | Q(sql_content__icontains=keyword)
                | Q(username__icontains=keyword)
            )

        create_time_from = _parse_datetime_param(request.query_params.get("create_time_from"))
        if create_time_from:
            qs = qs.filter(create_time__gte=create_time_from)

        create_time_to = _parse_datetime_param(request.query_params.get("create_time_to"))
        if create_time_to:
            qs = qs.filter(create_time__lte=create_time_to)

        paginator = OperateLogPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = OperateLogSerializer(page, many=True)
        return success_response(
            {
                "count": paginator.page.paginator.count,
                "results": serializer.data,
            }
        )


@extend_schema(tags=["logs"])
class StorageStatsView(APIView):
    """GET /api/logs/stats/ — image and storage statistics (admin only)."""

    permission_classes = [IsAuthenticated, IsActiveAccount, IsAdminRole]

    def get(self, request):
        return success_response(compute_storage_stats())
