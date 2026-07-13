"""Admin API for BLOB → upload/ migration."""
from __future__ import annotations

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from images.blob_migration_job_service import (
    JobServiceError,
    cancel_migration_job,
    clear_migration_job_history,
    create_migration_job,
    delete_migration_job,
    export_job_errors_csv,
    list_migration_jobs,
    pause_migration_job,
    resume_migration_job,
    serialize_migration_job,
)
from images.blob_migration_service import (
    BlobMigrationError,
    count_live_map_entries_by_source_table,
    count_migration_candidates,
    create_migration_source,
    discover_blob_tables,
    run_blob_migration,
)
from images.models import BlobMigrationJob, BlobMigrationSource
from images.serializers import (
    BlobMigrationDiscoverSerializer,
    BlobMigrationJobCreateSerializer,
    BlobMigrationJobClearSerializer,
    BlobMigrationJobRetrySerializer,
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
                "source_column": item.source_column,
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
        include_stats = str(request.query_params.get("include_stats", "0")).lower() in {
            "1",
            "true",
            "yes",
        }
        data = []
        for source in qs:
            entry = BlobMigrationSourceSerializer(source).data
            if include_stats:
                try:
                    entry["stats"] = count_migration_candidates(source.id)
                except BlobMigrationError:
                    entry["stats"] = None
            else:
                # Avoid blocking the whole list on expensive remote COUNT scans.
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
        # Stats are optional: a slow COUNT must not make "save" look like it failed.
        include_stats = str(request.query_params.get("include_stats", "0")).lower() in {
            "1",
            "true",
            "yes",
        }
        if include_stats:
            try:
                payload["stats"] = count_migration_candidates(source.id)
            except Exception:
                payload["stats"] = None
        else:
            payload["stats"] = None
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
        include_stats = str(request.query_params.get("include_stats", "0")).lower() in {
            "1",
            "true",
            "yes",
        }
        if include_stats:
            try:
                payload["stats"] = count_migration_candidates(source.id)
            except BlobMigrationError as exc:
                payload["stats"] = {"error": str(exc)}
            except Exception as exc:
                payload["stats"] = {"error": str(exc)}
        else:
            payload["stats"] = None
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


@extend_schema(tags=["blob-migration"], request=BlobMigrationJobCreateSerializer)
class BlobMigrationJobListCreateView(APIView):
    """GET/POST /api/images/blob-migration/jobs/ — list or create background migration jobs."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        source_id = request.query_params.get("source_id")
        parsed_source = None
        if source_id not in (None, ""):
            try:
                parsed_source = int(source_id)
            except (TypeError, ValueError):
                return error_response("source_id 无效", code=4001, status=400)
        jobs = list_migration_jobs(source_id=parsed_source, limit=50)
        return success_response(
            [
                serialize_migration_job(job, include_recent_errors=False)
                for job in jobs
            ]
        )

    def post(self, request):
        serializer = BlobMigrationJobCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        data = serializer.validated_data
        try:
            job = create_migration_job(
                source_id=data["source_id"],
                created_by=request.user.username,
                batch_size=data.get("batch_size", 50),
                dry_run=data.get("dry_run", False),
                skip_existing=data.get("skip_existing", True),
                run_all=data.get("run_all", True),
                warm_thumbs_after=data.get("warm_thumbs_after", True),
            )
        except JobServiceError as exc:
            return error_response(str(exc), code=4001, status=400)

        write_operate_log(
            request,
            "blob_migration_job",
            detail=f"job_id={job.id} source_id={job.source_id} run_all={job.run_all}",
        )
        return success_response(
            serialize_migration_job(job),
            message="迁移任务已创建，scheduler 将自动开始（约 10 秒内）",
            status=201,
        )


@extend_schema(tags=["blob-migration"])
class BlobMigrationJobDetailView(APIView):
    """GET/DELETE /api/images/blob-migration/jobs/{id}/ — job progress or delete."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request, pk: int):
        try:
            job = BlobMigrationJob.objects.get(pk=pk)
        except BlobMigrationJob.DoesNotExist:
            return error_response("任务不存在", code=4044, status=404)
        return success_response(serialize_migration_job(job))

    def delete(self, request, pk: int):
        try:
            delete_migration_job(pk)
        except JobServiceError as exc:
            return error_response(str(exc), code=4001, status=400)
        write_operate_log(request, "blob_migration_job_delete", detail=f"job_id={pk}")
        return success_response(None, message="任务记录已删除")


@extend_schema(tags=["blob-migration"], request=BlobMigrationJobClearSerializer)
class BlobMigrationJobClearView(APIView):
    """POST /api/images/blob-migration/jobs/clear/ — delete finished job history."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request):
        serializer = BlobMigrationJobClearSerializer(data=request.data or {})
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        source_id = serializer.validated_data.get("source_id")
        deleted = clear_migration_job_history(source_id=source_id)
        scope = f"source_id={source_id}" if source_id else "all"
        write_operate_log(request, "blob_migration_job_clear", detail=f"{scope} deleted={deleted}")
        return success_response(
            {"deleted": deleted},
            message=f"已清除 {deleted} 条历史记录" if deleted else "没有可清除的历史记录",
        )


@extend_schema(tags=["blob-migration"])
class BlobMigrationJobCancelView(APIView):
    """POST /api/images/blob-migration/jobs/{id}/cancel/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request, pk: int):
        try:
            job = cancel_migration_job(pk)
        except JobServiceError as exc:
            return error_response(str(exc), code=4001, status=400)
        write_operate_log(request, "blob_migration_job_cancel", detail=f"job_id={job.id}")
        return success_response(serialize_migration_job(job), message="已请求取消")


@extend_schema(tags=["blob-migration"])
class BlobMigrationJobPauseView(APIView):
    """POST /api/images/blob-migration/jobs/{id}/pause/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request, pk: int):
        try:
            job = pause_migration_job(pk)
        except JobServiceError as exc:
            return error_response(str(exc), code=4001, status=400)
        write_operate_log(request, "blob_migration_job_pause", detail=f"job_id={job.id}")
        message = "已暂停" if job.status == BlobMigrationJob.STATUS_PAUSED else "正在暂停…"
        return success_response(serialize_migration_job(job), message=message)


@extend_schema(tags=["blob-migration"])
class BlobMigrationJobResumeView(APIView):
    """POST /api/images/blob-migration/jobs/{id}/resume/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request, pk: int):
        try:
            job = resume_migration_job(pk)
        except JobServiceError as exc:
            return error_response(str(exc), code=4001, status=400)
        write_operate_log(request, "blob_migration_job_resume", detail=f"job_id={job.id}")
        return success_response(serialize_migration_job(job), message="已排队，scheduler 将继续执行")


@extend_schema(tags=["blob-migration"], request=BlobMigrationJobRetrySerializer)
class BlobMigrationJobRetryView(APIView):
    """POST /api/images/blob-migration/jobs/retry/ — retry failed rows from a prior job."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request):
        serializer = BlobMigrationJobRetrySerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        data = serializer.validated_data
        parent = BlobMigrationJob.objects.filter(pk=data["parent_job_id"]).first()
        if parent is None:
            return error_response("来源任务不存在", code=4044, status=404)
        try:
            job = create_migration_job(
                source_id=parent.source_id,
                created_by=request.user.username,
                batch_size=data.get("batch_size", 50),
                dry_run=data.get("dry_run", False),
                skip_existing=False,
                run_all=True,
                warm_thumbs_after=data.get("warm_thumbs_after", True),
                retry_failed_only=True,
                parent_job_id=parent.id,
            )
        except JobServiceError as exc:
            return error_response(str(exc), code=4001, status=400)
        write_operate_log(
            request,
            "blob_migration_job_retry",
            detail=f"job_id={job.id} parent={parent.id}",
        )
        return success_response(serialize_migration_job(job), message="重试任务已创建，scheduler 将自动开始", status=201)


@extend_schema(tags=["blob-migration"])
class BlobMigrationJobErrorsExportView(APIView):
    """GET /api/images/blob-migration/jobs/{id}/errors/export/ — CSV download."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request, pk: int):
        try:
            csv_text = export_job_errors_csv(pk)
        except JobServiceError as exc:
            return error_response(str(exc), code=4044, status=404)
        response = HttpResponse(csv_text, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="blob_migration_job_{pk}_errors.csv"'
        return response


@extend_schema(tags=["blob-migration"])
class BlobMigrationMapStatsView(APIView):
    """GET /api/images/blob-migration/map-stats/ — live image_source_map counts by source_table."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        return success_response({"by_source_table": count_live_map_entries_by_source_table()})


def _format_errors(errors: dict) -> str:
    if not errors:
        return "请求参数错误"
    parts = []
    for key, val in errors.items():
        msg = val[0] if isinstance(val, list) else val
        parts.append(f"{key}: {msg}")
    return "; ".join(parts)
