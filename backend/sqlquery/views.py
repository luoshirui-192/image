"""SQL query API — Step 13."""
from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from sqlquery.serializers import SqlExecuteSerializer
from sqlquery.services import SqlExecutionError, execute_select_sql
from utils.audit import write_operate_log
from utils.permissions import IsActiveAccount, IsAdminRole
from utils.responses import error_response, success_response
from utils.sql_validator import SqlValidationError, validate_sql


@extend_schema(
    tags=["sql"],
    request=SqlExecuteSerializer,
    examples=[
        OpenApiExample(
            "查询图片列表",
            value={"sql": "SELECT id, image_name, image_path FROM image_info WHERE is_delete = 0 LIMIT 10"},
            request_only=True,
        ),
    ],
)
class SqlExecuteView(APIView):
    """POST /api/sql/execute/ — admin-only SELECT execution."""

    permission_classes = [IsAuthenticated, IsActiveAccount, IsAdminRole]

    def post(self, request):
        serializer = SqlExecuteSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)

        sql = serializer.validated_data["sql"]

        try:
            result = execute_select_sql(sql)
        except SqlValidationError as exc:
            write_operate_log(
                request,
                "sql_execute",
                sql_content=sql[:2000],
                detail=f"rejected: {exc}",
            )
            return error_response(str(exc), code=4001, status=400)
        except SqlExecutionError as exc:
            write_operate_log(
                request,
                "sql_execute",
                sql_content=sql[:2000],
                detail=f"failed: {exc}",
            )
            return error_response(str(exc), code=4002, status=400)

        write_operate_log(
            request,
            "sql_execute",
            sql_content=result["sql"][:2000],
            detail=f"rows={result['row_count']} elapsed={result['elapsed_ms']}ms truncated={result['truncated']}",
        )

        return success_response(result, message="查询成功")


@extend_schema(
    tags=["sql"],
    request=SqlExecuteSerializer,
    examples=[
        OpenApiExample(
            "校验 SQL",
            value={"sql": "SELECT * FROM image_info"},
            request_only=True,
        ),
    ],
)
class SqlValidateView(APIView):
    """POST /api/sql/validate/ — validate SQL without executing (admin)."""

    permission_classes = [IsAuthenticated, IsActiveAccount, IsAdminRole]

    def post(self, request):
        serializer = SqlExecuteSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)

        sql = serializer.validated_data["sql"]
        try:
            from django.conf import settings

            cleaned = validate_sql(
                sql,
                require_where_for_select_star=getattr(settings, "SQL_REQUIRE_WHERE_FOR_SELECT_STAR", False),
            )
        except SqlValidationError as exc:
            return error_response(str(exc), code=4001, status=400)

        return success_response({"sql": cleaned, "valid": True}, message="SQL 校验通过")


def _format_errors(errors: dict) -> str:
    if not errors:
        return "请求参数错误"
    parts = []
    for key, val in errors.items():
        msg = val[0] if isinstance(val, list) else val
        parts.append(f"{key}: {msg}")
    return "; ".join(parts)
