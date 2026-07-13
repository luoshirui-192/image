"""API views for external BLOB auto-sync."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from images.blob_migration_service import BlobMigrationError, _load_source
from images.blob_sync_detect import refresh_source_change_track
from images.blob_sync_service import (
    BlobSyncError,
    backfill_source_sync_fingerprints,
    count_sync_stats,
    run_detect_and_resync_for_source,
)
from images.blob_migration_service import _source_db_session
from images.models import BlobMigrationSource
from images.serializers import (
    BlobMigrationSourceSyncUpdateSerializer,
    BlobSyncBackfillSerializer,
)
from utils.audit import write_operate_log
from utils.permissions import IsActiveAccount
from utils.responses import error_response, success_response


def _format_errors(errors: dict) -> str:
    if not errors:
        return "请求参数错误"
    parts = []
    for key, val in errors.items():
        msg = val[0] if isinstance(val, list) else val
        parts.append(f"{key}: {msg}")
    return "; ".join(parts)


def _get_source(pk: int) -> BlobMigrationSource | None:
    try:
        return BlobMigrationSource.objects.get(pk=pk)
    except BlobMigrationSource.DoesNotExist:
        return None


def _serialize_sync_status(source: BlobMigrationSource) -> dict:
    stats = count_sync_stats(source.id)
    return {
        "source_id": source.id,
        "auto_sync_enabled": bool(source.auto_sync_enabled),
        "sync_interval_minutes": int(source.sync_interval_minutes or 60),
        "sync_batch_size": int(source.sync_batch_size or 200),
        "sync_last_run_at": source.sync_last_run_at.isoformat(sep=" ", timespec="seconds")
        if source.sync_last_run_at
        else None,
        "sync_last_checked_map_id": int(source.sync_last_checked_map_id or 0),
        "change_track_mode": getattr(source, "change_track_mode", "") or "hash",
        "change_track_column": getattr(source, "change_track_column", "") or "",
        "stats": stats,
    }


@extend_schema(tags=["blob-migration"])
class BlobMigrationSourceSyncStatusView(APIView):
    """GET /api/images/blob-migration/sources/{id}/sync/status/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request, pk: int):
        source = _get_source(pk)
        if source is None:
            return error_response("迁移配置不存在", code=4044, status=404)
        return success_response(_serialize_sync_status(source))


@extend_schema(tags=["blob-migration"], request=BlobMigrationSourceSyncUpdateSerializer)
class BlobMigrationSourceSyncSettingsView(APIView):
    """PATCH /api/images/blob-migration/sources/{id}/sync/settings/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def patch(self, request, pk: int):
        source = _get_source(pk)
        if source is None:
            return error_response("迁移配置不存在", code=4044, status=404)

        serializer = BlobMigrationSourceSyncUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)

        data = serializer.validated_data
        updates = {}
        if "auto_sync_enabled" in data:
            updates["auto_sync_enabled"] = 1 if data["auto_sync_enabled"] else 0
        if "sync_interval_minutes" in data:
            updates["sync_interval_minutes"] = data["sync_interval_minutes"]
        if "sync_batch_size" in data:
            updates["sync_batch_size"] = data["sync_batch_size"]
        if updates:
            BlobMigrationSource.objects.filter(pk=pk).update(**updates)
            for key, val in updates.items():
                setattr(source, key, val)

        if data.get("refresh_change_track"):
            try:
                with _source_db_session(source) as alias:
                    refresh_source_change_track(source, conn_alias=alias)
            except Exception as exc:
                return error_response(f"探测变更列失败: {exc}", code=4001, status=400)

        write_operate_log(request, "blob_sync_settings", detail=f"source_id={pk} {updates}")
        return success_response(_serialize_sync_status(_get_source(pk)), message="同步设置已更新")


@extend_schema(tags=["blob-migration"], request=BlobSyncBackfillSerializer)
class BlobMigrationSourceSyncBackfillView(APIView):
    """POST /api/images/blob-migration/sources/{id}/sync/backfill/"""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request, pk: int):
        source = _get_source(pk)
        if source is None:
            return error_response("迁移配置不存在", code=4044, status=404)

        serializer = BlobSyncBackfillSerializer(data=request.data or {})
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        data = serializer.validated_data
        try:
            result = backfill_source_sync_fingerprints(
                source_id=pk,
                lookup_table=data.get("table") or None,
                batch_size=data.get("batch_size"),
                limit=data.get("limit"),
                dry_run=data.get("dry_run", False),
            )
        except BlobSyncError as exc:
            return error_response(str(exc), code=4001, status=400)

        write_operate_log(
            request,
            "blob_sync_backfill",
            detail=f"source_id={pk} checked={result.checked} changed={result.changed}",
        )
        return success_response(
            {
                "checked": result.checked,
                "changed": result.changed,
                "failed": result.failed,
                "errors": result.errors[:20],
            },
            message="指纹回填完成" if not data.get("dry_run") else "预检完成",
        )


@extend_schema(tags=["blob-migration"])
class BlobMigrationSourceSyncRunView(APIView):
    """POST /api/images/blob-migration/sources/{id}/sync/run/ — detect + resync now."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request, pk: int):
        source = _get_source(pk)
        if source is None:
            return error_response("迁移配置不存在", code=4044, status=404)
        try:
            result = run_detect_and_resync_for_source(pk, actor=request.user.username)
        except BlobMigrationError as exc:
            return error_response(str(exc), code=4001, status=400)
        except BlobSyncError as exc:
            return error_response(str(exc), code=4001, status=400)

        write_operate_log(
            request,
            "blob_sync_run",
            detail=(
                f"source_id={pk} checked={result.checked} changed={result.changed} "
                f"resynced={result.resynced} failed={result.failed}"
            ),
        )
        return success_response(
            {
                "checked": result.checked,
                "changed": result.changed,
                "resynced": result.resynced,
                "failed": result.failed,
                "stats": count_sync_stats(pk),
            },
            message="同步完成",
        )


@extend_schema(tags=["blob-migration"], request=BlobSyncBackfillSerializer)
class BlobSyncGlobalBackfillView(APIView):
    """POST /api/images/blob-migration/sync/backfill/ — backfill all map rows."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request):
        serializer = BlobSyncBackfillSerializer(data=request.data or {})
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)
        data = serializer.validated_data
        try:
            result = backfill_source_sync_fingerprints(
                lookup_table=data.get("table") or None,
                batch_size=data.get("batch_size"),
                limit=data.get("limit"),
                dry_run=data.get("dry_run", False),
            )
        except BlobSyncError as exc:
            return error_response(str(exc), code=4001, status=400)

        write_operate_log(
            request,
            "blob_sync_backfill_all",
            detail=f"checked={result.checked} changed={result.changed}",
        )
        return success_response(
            {
                "checked": result.checked,
                "changed": result.changed,
                "failed": result.failed,
                "errors": result.errors[:20],
            },
            message="全局指纹回填完成" if not data.get("dry_run") else "预检完成",
        )
