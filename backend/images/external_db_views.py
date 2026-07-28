"""Admin API for external MySQL connections configured from Web UI."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from django.utils import timezone

from images.external_db_service import (
    ExternalDbError,
    create_external_connection,
    list_database_aliases,
    serialize_connection,
    test_connection_payload,
    test_external_connection,
    update_external_connection,
)
from images.blob_table_view_service import auto_provision_table_views_for_connection
from images.models import BlobMigrationSource, ExternalDbConnection
from images.serializers import ExternalDbConnectionSerializer, ExternalDbConnectionTestSerializer
from utils.audit import write_operate_log
from utils.permissions import IsActiveAccount
from utils.responses import error_response, success_response


@extend_schema(tags=["blob-migration"])
class BlobMigrationDatabaseListView(APIView):
    """GET /api/images/blob-migration/databases/ — system + Web-configured DB aliases."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        return success_response(list_database_aliases())


@extend_schema(tags=["blob-migration"])
class ExternalDbConnectionListCreateView(APIView):
    """GET/POST /api/images/blob-migration/connections/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        records = ExternalDbConnection.objects.all().order_by("-id")
        return success_response([serialize_connection(item) for item in records])

    def post(self, request):
        serializer = ExternalDbConnectionSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        data = serializer.validated_data
        if not data.get("password"):
            return error_response("password: 新建连接必须填写密码", code=4001, status=400)
        try:
            record = create_external_connection(**data)
        except ExternalDbError as exc:
            return error_response(str(exc), code=4001, status=400)

        provision = auto_provision_table_views_for_connection(record)
        write_operate_log(request, "external_db_create", detail=f"name={record.name} host={record.host}")
        message = _format_provision_message("旧库连接已保存", provision)
        payload = serialize_connection(record)
        payload["table_view_provision"] = provision
        return success_response(payload, message=message, status=201)


@extend_schema(tags=["blob-migration"])
class ExternalDbConnectionDetailView(APIView):
    """PATCH/DELETE /api/images/blob-migration/connections/{id}/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def _get_record(self, pk: int):
        try:
            return ExternalDbConnection.objects.get(pk=pk)
        except ExternalDbConnection.DoesNotExist:
            return None

    def patch(self, request, pk: int):
        record = self._get_record(pk)
        if record is None:
            return error_response("连接不存在", code=4044, status=404)

        serializer = ExternalDbConnectionSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)

        try:
            updated = update_external_connection(record, **serializer.validated_data)
        except ExternalDbError as exc:
            return error_response(str(exc), code=4001, status=400)

        write_operate_log(request, "external_db_update", detail=f"id={pk} name={updated.name}")
        return success_response(serialize_connection(updated), message="连接已更新")

    def delete(self, request, pk: int):
        record = self._get_record(pk)
        if record is None:
            return error_response("连接不存在", code=4044, status=404)

        alias = f"external_{pk}"
        if BlobMigrationSource.objects.filter(db_alias=alias).exists():
            return error_response("仍有迁移任务引用此连接，请先删除相关任务", code=4005, status=400)

        name = record.name
        record.delete()
        write_operate_log(request, "external_db_delete", detail=f"name={name}")
        return success_response(None, message="连接已删除")


@extend_schema(tags=["blob-migration"], request=ExternalDbConnectionTestSerializer)
class ExternalDbConnectionTestView(APIView):
    """POST /api/images/blob-migration/connections/test/ — test unsaved connection."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request):
        serializer = ExternalDbConnectionTestSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        try:
            message = test_connection_payload(**serializer.validated_data)
        except ExternalDbError as exc:
            return error_response(str(exc), code=4001, status=400)
        return success_response({"ok": True, "message": message}, message=message)


@extend_schema(tags=["blob-migration"])
class ExternalDbConnectionTestSavedView(APIView):
    """POST /api/images/blob-migration/connections/{id}/test/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request, pk: int):
        try:
            record = ExternalDbConnection.objects.get(pk=pk)
        except ExternalDbConnection.DoesNotExist:
            return error_response("连接不存在", code=4044, status=404)

        password = request.data.get("password")
        try:
            if password:
                message = test_connection_payload(
                    name=record.name,
                    host=record.host,
                    port=record.port,
                    db_name=record.db_name,
                    username=record.username,
                    password=password,
                    charset=record.charset,
                )
            else:
                message = test_external_connection(record)
        except ExternalDbError as exc:
            record.last_test_at = timezone.now()
            record.last_test_ok = 0
            record.last_test_message = str(exc)[:500]
            record.save(update_fields=["last_test_at", "last_test_ok", "last_test_message"])
            return error_response(str(exc), code=4001, status=400)

        write_operate_log(request, "external_db_test", detail=f"id={pk} ok=1")
        return success_response({"ok": True, "message": message}, message=message)


@extend_schema(tags=["blob-migration"])
class ExternalDbConnectionProvisionTableViewsView(APIView):
    """POST /api/images/blob-migration/connections/{id}/provision-table-views/ — sync saved table views."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request, pk: int):
        try:
            record = ExternalDbConnection.objects.get(pk=pk)
        except ExternalDbConnection.DoesNotExist:
            return error_response("连接不存在", code=4044, status=404)

        provision = auto_provision_table_views_for_connection(record)
        write_operate_log(
            request,
            "external_db_provision_views",
            detail=(
                f"id={pk} created={provision.get('created', 0)} "
                f"skipped={provision.get('skipped', 0)} failed={provision.get('failed', 0)}"
            ),
        )
        message = _format_provision_message("表视图同步完成", provision)
        return success_response(
            {
                "connection_id": pk,
                "table_view_provision": provision,
            },
            message=message,
        )


def _format_provision_message(prefix: str, provision: dict) -> str:
    created = int(provision.get("created") or 0)
    skipped = int(provision.get("skipped") or 0)
    failed = int(provision.get("failed") or 0)
    errors = provision.get("errors") or []

    if errors and not created and not skipped and not failed:
        return f"{prefix}：{errors[0]}"

    parts = [prefix]
    detail_parts: list[str] = []
    if created:
        detail_parts.append(f"新增 {created} 个")
    if skipped:
        detail_parts.append(f"跳过 {skipped} 个")
    if failed:
        detail_parts.append(f"失败 {failed} 个")
    if detail_parts:
        parts.append("（" + "，".join(detail_parts) + "）")
    return "".join(parts)


def _format_errors(errors: dict) -> str:
    if not errors:
        return "请求参数错误"
    parts = []
    for key, val in errors.items():
        msg = val[0] if isinstance(val, list) else val
        parts.append(f"{key}: {msg}")
    return "; ".join(parts)
