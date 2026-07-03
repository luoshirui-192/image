"""Admin API for BLOB → upload/ migration."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from images.blob_migration_service import (
    BlobMigrationError,
    count_migration_candidates,
    create_migration_source,
    discover_blob_tables,
    run_blob_migration,
)
from images.models import BlobMigrationSource
from images.serializers import (
    BlobMigrationDiscoverSerializer,
    BlobMigrationRunSerializer,
    BlobMigrationSourceSerializer,
)
from utils.audit import write_operate_log
from utils.permissions import IsActiveAccount
from utils.responses import error_response, success_response


def _serialize_run_result(result):
    return {
        "source_id": result.source_id,
        "source_table": result.source_table,
        "dry_run": result.dry_run,
        "total_candidates": result.total_candidates,
        "processed": result.processed,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "skipped": result.skipped,
        "items": [
            {
                "source_id": item.source_id,
                "success": item.success,
                "skipped": item.skipped,
                "image_info_id": item.image_info_id,
                "filename": item.filename,
                "error": item.error,
            }
            for item in result.items
        ],
    }


@extend_schema(tags=["blob-migration"], request=BlobMigrationDiscoverSerializer)
class BlobMigrationDiscoverView(APIView):
    """POST /api/images/blob-migration/discover/ — list tables with BLOB columns."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request):
        serializer = BlobMigrationDiscoverSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        try:
            tables = discover_blob_tables(db_alias=serializer.validated_data.get("db_alias", "default"))
        except BlobMigrationError as exc:
            return error_response(str(exc), code=4001, status=400)
        return success_response({"tables": tables})


@extend_schema(tags=["blob-migration"])
class BlobMigrationSourceListCreateView(APIView):
    """GET/POST /api/images/blob-migration/sources/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        qs = BlobMigrationSource.objects.all().order_by("-id")
        data = []
        for source in qs:
            entry = BlobMigrationSourceSerializer(source).data
            try:
                entry["stats"] = count_migration_candidates(source.id)
            except BlobMigrationError:
                entry["stats"] = None
            data.append(entry)
        return success_response(data)

    def post(self, request):
        serializer = BlobMigrationSourceSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        try:
            source = create_migration_source(**serializer.validated_data)
        except BlobMigrationError as exc:
            return error_response(str(exc), code=4001, status=400)

        write_operate_log(
            request,
            "blob_migration_config",
            detail=f"source={source.source_table} blob={source.blob_column}",
        )
        payload = BlobMigrationSourceSerializer(source).data
        payload["stats"] = count_migration_candidates(source.id)
        return success_response(payload, message="迁移配置已保存", status=201)


@extend_schema(tags=["blob-migration"])
class BlobMigrationSourceDetailView(APIView):
    """GET/DELETE /api/images/blob-migration/sources/{id}/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def _get_source(self, pk: int):
        try:
            return BlobMigrationSource.objects.get(pk=pk)
        except BlobMigrationSource.DoesNotExist:
            return None

    def get(self, request, pk: int):
        source = self._get_source(pk)
        if source is None:
            return error_response("迁移配置不存在", code=4044, status=404)
        payload = BlobMigrationSourceSerializer(source).data
        try:
            payload["stats"] = count_migration_candidates(source.id)
        except BlobMigrationError as exc:
            payload["stats"] = {"error": str(exc)}
        return success_response(payload)

    def delete(self, request, pk: int):
        source = self._get_source(pk)
        if source is None:
            return error_response("迁移配置不存在", code=4044, status=404)
        name = source.name or source.source_table
        source.delete()
        write_operate_log(request, "blob_migration_config_delete", detail=f"source={name}")
        return success_response(None, message="迁移配置已删除")


@extend_schema(tags=["blob-migration"], request=BlobMigrationRunSerializer)
class BlobMigrationRunView(APIView):
    """POST /api/images/blob-migration/run/ — execute migration batch."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request):
        serializer = BlobMigrationRunSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)

        data = serializer.validated_data
        try:
            result = run_blob_migration(
                data["source_id"],
                batch_size=data.get("batch_size", 50),
                dry_run=data.get("dry_run", False),
                skip_existing=data.get("skip_existing", True),
                upload_user=request.user.username,
            )
        except BlobMigrationError as exc:
            return error_response(str(exc), code=4001, status=400)

        summary = _serialize_run_result(result)
        verb = "预检" if result.dry_run else "迁移"
        write_operate_log(
            request,
            "blob_migration_run",
            detail=(
                f"{verb} source_id={result.source_id} processed={result.processed} "
                f"ok={result.succeeded} skip={result.skipped} fail={result.failed}"
            ),
        )
        return success_response(
            summary,
            message=(
                f"{verb}完成：处理 {result.processed} 条，"
                f"成功 {result.succeeded}，跳过 {result.skipped}，失败 {result.failed}"
            ),
        )


def _format_errors(errors: dict) -> str:
    if not errors:
        return "请求参数错误"
    parts = []
    for key, val in errors.items():
        msg = val[0] if isinstance(val, list) else val
        parts.append(f"{key}: {msg}")
    return "; ".join(parts)
