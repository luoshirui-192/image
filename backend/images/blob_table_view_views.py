"""Admin API for saved virtual BLOB table views."""
from __future__ import annotations

import logging

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from images.blob_simulated_export_service import (
    SimulatedExportError,
    export_simulated_table_to_connection,
)
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
from images.models import BlobTableView
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
    """POST /api/images/blob-browse/{id}/export-to-connection/ — write path table to another DB."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request, pk: int):
        serializer = BlobSimulatedExportSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        data = serializer.validated_data
        try:
            result = export_simulated_table_to_connection(
                pk,
                target_connection_id=data.get("target_connection_id"),
                target_db_alias=data.get("target_db_alias") or None,
                target_database=data.get("target_database") or "",
                target_table=data.get("target_table") or "",
                if_exists=data.get("if_exists") or "fail",
            )
        except SimulatedExportError as exc:
            return error_response(str(exc), code=4001, status=400)
        except BlobTableViewError as exc:
            return error_response(str(exc), code=4001, status=400)
        except Exception:
            logger.exception("export_simulated_table failed view_id=%s", pk)
            return error_response("导出到目标库失败", code=5001, status=500)

        write_operate_log(
            request,
            "blob_table_export_to_connection",
            detail=(
                f"view_id={pk} target={result.get('target_db_alias')}."
                f"{result.get('target_database')}.{result.get('target_table')} "
                f"rows={result.get('rows_written')}"
            ),
        )
        return success_response(result, message="已导出到目标库")
