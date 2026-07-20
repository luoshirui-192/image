"""Admin API for saved virtual BLOB table views."""
from __future__ import annotations

import logging

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from images.blob_simulated_export_job_service import (
    cancel_export_job,
    create_export_job,
    kick_export_job_async,
    kick_export_queue,
    pause_export_job,
    resume_export_job,
    serialize_export_job,
)
from images.blob_simulated_export_service import SimulatedExportError
from images.blob_table_view_service import (
    BlobTableViewError,
    count_view_rows,
    create_table_view,
    delete_table_view,
    fetch_view_rows,
    get_view_schema,
    preview_table_schema,
    update_table_view,
)
from images.external_db_service import list_database_aliases
from images.models import BlobSimulatedExportJob, BlobTableView
from images.serializers import (
    BlobSimulatedExportSerializer,
    BlobTableViewCreateSerializer,
    BlobTableViewPreviewSchemaSerializer,
    BlobTableViewRowsSerializer,
    BlobTableViewSerializer,
    BlobTableViewUpdateSerializer,
)
from utils.audit import write_operate_log
from utils.permissions import IsActiveAccount
from utils.responses import error_response, success_response

logger = logging.getLogger(__name__)


def _format_errors(errors: dict) -> str:
    if not errors:
        return "请求参数错误"
    parts = []
    for key, val in errors.items():
        msg = val[0] if isinstance(val, list) else val
        parts.append(f"{key}: {msg}")
    return "; ".join(parts)


def _db_label_map() -> dict[str, str]:
    labels: dict[str, str] = {}
    try:
        for entry in list_database_aliases():
            labels[entry["alias"]] = entry.get("label") or entry.get("name") or entry["alias"]
    except Exception:
        logger.warning("list_database_aliases failed", exc_info=True)
    return labels


def _serialize_view(view: BlobTableView, *, include_stats: bool = False) -> dict:
    payload = BlobTableViewSerializer(view).data
    labels = _db_label_map()
    payload["db_label"] = labels.get(view.db_alias, view.db_alias)
    if include_stats:
        try:
            payload["row_count"] = count_view_rows(view.id)
        except BlobTableViewError as exc:
            payload["row_count"] = None
            payload["stats_error"] = str(exc)
    return payload


@extend_schema(tags=["blob-table-view"])
class BlobTableViewListCreateView(APIView):
    """GET/POST /api/images/blob-migration/table-views/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        views = BlobTableView.objects.all().order_by("-id")
        # Never COUNT remote tables for every saved view on page load — that stalls workers.
        include_stats = str(request.query_params.get("include_stats", "0")).lower() in {
            "1",
            "true",
            "yes",
        }
        data = [_serialize_view(view, include_stats=include_stats) for view in views]
        return success_response(data)

    def post(self, request):
        serializer = BlobTableViewCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        data = serializer.validated_data
        try:
            view = create_table_view(**data)
        except BlobTableViewError as exc:
            return error_response(str(exc), code=4001, status=400)

        write_operate_log(
            request,
            "blob_table_view_create",
            detail=f"view={view.name} table={view.source_table}",
        )
        return success_response(
            _serialize_view(view, include_stats=False),
            message="表视图已保存",
            status=201,
        )


@extend_schema(tags=["blob-table-view"])
class BlobTableViewDetailView(APIView):
    """GET/PATCH/DELETE /api/images/blob-migration/table-views/{id}/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def _get_view(self, pk: int):
        try:
            return BlobTableView.objects.get(pk=pk)
        except BlobTableView.DoesNotExist:
            return None

    def get(self, request, pk: int):
        view = self._get_view(pk)
        if view is None:
            return error_response("表视图不存在", code=4044, status=404)
        return success_response(_serialize_view(view, include_stats=False))

    def patch(self, request, pk: int):
        view = self._get_view(pk)
        if view is None:
            return error_response("表视图不存在", code=4044, status=404)
        serializer = BlobTableViewUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        try:
            updated = update_table_view(pk, **serializer.validated_data)
        except BlobTableViewError as exc:
            return error_response(str(exc), code=4001, status=400)
        write_operate_log(request, "blob_table_view_update", detail=f"view_id={pk}")
        return success_response(_serialize_view(updated, include_stats=False), message="已更新")

    def delete(self, request, pk: int):
        view = self._get_view(pk)
        if view is None:
            return error_response("表视图不存在", code=4044, status=404)
        name = view.name or view.source_table
        try:
            delete_table_view(pk)
        except BlobTableViewError as exc:
            return error_response(str(exc), code=4001, status=400)
        write_operate_log(request, "blob_table_view_delete", detail=f"view={name}")
        return success_response(None, message="表视图已删除")


@extend_schema(tags=["blob-table-view"])
class BlobTableViewSchemaView(APIView):
    """GET /api/images/blob-migration/table-views/{id}/schema/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request, pk: int):
        try:
            schema = get_view_schema(pk)
        except BlobTableViewError as exc:
            return error_response(str(exc), code=4001, status=400)
        return success_response(schema)


@extend_schema(tags=["blob-table-view"], request=BlobTableViewRowsSerializer)
class BlobTableViewRowsView(APIView):
    """GET /api/images/blob-migration/table-views/{id}/rows/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request, pk: int):
        serializer = BlobTableViewRowsSerializer(data=request.query_params)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        data = serializer.validated_data
        try:
            payload = fetch_view_rows(
                pk,
                offset=data.get("offset", 0),
                limit=data.get("limit", 100),
                include_total=data.get("include_total", True),
                skip_blob_presence=data.get("skip_blob_presence", False),
            )
        except BlobTableViewError as exc:
            return error_response(str(exc), code=4001, status=400)
        except Exception:
            logger.exception("fetch_view_rows failed view_id=%s", pk)
            return error_response("加载表视图数据失败", code=5001, status=500)
        return success_response(payload)


@extend_schema(tags=["blob-table-view"], request=BlobTableViewPreviewSchemaSerializer)
class BlobTableViewPreviewSchemaView(APIView):
    """POST /api/images/blob-migration/table-views/preview-schema/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request):
        serializer = BlobTableViewPreviewSchemaSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        try:
            schema = preview_table_schema(**serializer.validated_data)
        except BlobTableViewError as exc:
            return error_response(str(exc), code=4001, status=400)
        return success_response(schema)


@extend_schema(tags=["blob-table-view"], request=BlobSimulatedExportSerializer)
class BlobTableViewExportToConnectionView(APIView):
    """POST /api/images/blob-browse/{id}/export-to-connection/ — start async export job."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request, pk: int):
        if not BlobTableView.objects.filter(pk=pk).exists():
            return error_response("浏览配置不存在", code=4041, status=404)
        serializer = BlobSimulatedExportSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        data = serializer.validated_data
        username = getattr(request.user, "username", "") or ""
        blocker = (
            BlobSimulatedExportJob.objects.filter(
                status__in={
                    BlobSimulatedExportJob.STATUS_RUNNING,
                    BlobSimulatedExportJob.STATUS_PAUSED,
                }
            )
            .order_by("id")
            .first()
        )
        try:
            job = create_export_job(
                view_id=pk,
                created_by=username,
                target_connection_id=data.get("target_connection_id"),
                target_db_alias=data.get("target_db_alias") or "",
                target_database=data.get("target_database") or "",
                target_table=data.get("target_table") or "",
                if_exists=data.get("if_exists") or "fail",
            )
            # Start this job immediately. Claim logic keeps exports serial.
            kick_export_job_async(job.id)
            kick_export_queue()
        except Exception:
            logger.exception("create export job failed view_id=%s", pk)
            return error_response("创建导出任务失败", code=5001, status=500)

        job = BlobSimulatedExportJob.objects.get(pk=job.id)
        write_operate_log(
            request,
            "export_job_start",
            detail=(
                f"job_id={job.id} view_id={pk} "
                f"target={job.target_db_alias or job.target_connection_id}."
                f"{job.target_database}.{job.target_table}"
            ),
        )
        msg = "导出任务已加入队列"
        if blocker and job.status == BlobSimulatedExportJob.STATUS_PENDING:
            msg = (
                f"导出任务已创建（#{job.id}），但队列被"
                f"{'进行中' if blocker.status == 'running' else '已暂停'}"
                f"任务 #{blocker.id} 占用；请到任务台继续/取消该任务，或等待其完成"
            )
        return success_response(
            {"job": serialize_export_job(job), "async": True, "blocked_by": blocker.id if blocker else None},
            message=msg,
            status=202,
        )


@extend_schema(tags=["blob-table-view"])
class BlobSimulatedExportJobDetailView(APIView):
    """GET/POST /api/images/blob-browse/export-jobs/{id}/ — status or cancel/pause/resume."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request, pk: int):
        job = BlobSimulatedExportJob.objects.filter(pk=pk).first()
        if not job:
            return error_response("导出任务不存在", code=4041, status=404)
        return success_response(serialize_export_job(job))

    def post(self, request, pk: int):
        action = str(request.data.get("action") or "").strip().lower()
        if action not in {"cancel", "pause", "resume"}:
            return error_response("仅支持 action=cancel|pause|resume", code=4001, status=400)
        try:
            if action == "cancel":
                job = cancel_export_job(pk)
                write_operate_log(request, "export_job_cancel", detail=f"job_id={pk}")
                return success_response(serialize_export_job(job), message="已请求取消")
            if action == "pause":
                job = pause_export_job(pk)
                write_operate_log(request, "export_job_pause", detail=f"job_id={pk}")
                return success_response(serialize_export_job(job), message="已请求暂停")
            job = resume_export_job(pk)
            write_operate_log(request, "export_job_resume", detail=f"job_id={pk}")
            return success_response(serialize_export_job(job), message="已重新排队")
        except SimulatedExportError as exc:
            return error_response(str(exc), code=4001, status=400)
