"""SQL template API — Step 13."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from sqlquery.serializers import SqlTemplateCreateSerializer
from sqlquery.template_store import add_template, list_templates
from utils.permissions import IsActiveAccount, IsAdminRole
from utils.responses import error_response, success_response


@extend_schema(tags=["sql"])
class SqlTemplateListCreateView(APIView):
    """GET/POST /api/sql/templates/ — list or save SQL templates (admin write)."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        return success_response(list_templates())

    def post(self, request):
        if not IsAdminRole().has_permission(request, self):
            return error_response("仅管理员可保存 SQL 模板", code=4030, status=403)

        serializer = SqlTemplateCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(str(serializer.errors), code=4001, status=400)

        try:
            entry = add_template(
                serializer.validated_data["name"],
                serializer.validated_data["sql"],
            )
        except ValueError as exc:
            return error_response(str(exc), code=4001, status=400)

        return success_response(entry, message="模板已保存", status=201)
