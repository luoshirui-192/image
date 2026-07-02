"""System settings API — Step 22."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from config.system_config import get_system_config, update_system_config
from utils.permissions import IsActiveAccount, IsAdminRole
from utils.responses import error_response, success_response


@extend_schema(tags=["config"])
class SystemConfigView(APIView):
    """GET/PATCH /api/config/ — read or update runtime system settings (admin)."""

    permission_classes = [IsAuthenticated, IsActiveAccount, IsAdminRole]

    def get(self, request):
        return success_response(get_system_config())

    def patch(self, request):
        try:
            data = update_system_config(request.data or {})
        except ValueError as exc:
            return error_response(str(exc), code=4001, status=400)
        return success_response(data, message="系统设置已更新")
