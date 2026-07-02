"""Image list/detail/update/delete API — Step 15."""
from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from images.batch_delete_service import batch_logical_delete, serialize_batch_delete_result
from images.deletion_policy import build_deletion_info, format_deletion_notice, get_retention_days
from images.models import ImageInfo
from images.querysets import filter_image_queryset, paginate_queryset, validate_category_id
from images.restore_service import RestoreError, restore_image
from images.serializers import (
    ImageBatchDeleteSerializer,
    ImageInfoSerializer,
    ImageInfoUpdateSerializer,
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


def _is_admin(user) -> bool:
    return getattr(user, "role", "") == "admin"


def _get_active_image(pk: int) -> ImageInfo | None:
    try:
        return ImageInfo.objects.get(pk=pk, is_delete=0)
    except ImageInfo.DoesNotExist:
        return None


def _logical_delete_image(image: ImageInfo) -> dict:
    image.is_delete = 1
    image.save(update_fields=["is_delete"])
    image.refresh_from_db()
    deletion_info = build_deletion_info(image.update_time)
    return {
        "image": ImageInfoSerializer(image).data,
        "deletion_info": deletion_info,
        "notice": format_deletion_notice(deletion_info),
    }


@extend_schema(tags=["images"])
class ImageDeletionPolicyView(APIView):
    """GET /api/images/deletion-policy/ — retention rules for logical delete."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        retention_days = get_retention_days()
        return success_response(
            {
                "retention_days": retention_days,
                "summary": (
                    f"逻辑删除后，图片文件将保留 {retention_days} 天，"
                    f"到期后由系统自动永久删除；保留期内可在列表中恢复。"
                ),
            }
        )


@extend_schema(
    tags=["images"],
    parameters=[
        OpenApiParameter("page", int, description="页码，默认 1"),
        OpenApiParameter("page_size", int, description="每页条数，默认 20，最大 100"),
        OpenApiParameter("category_id", int, description="分类 ID"),
        OpenApiParameter("tags", str, description="标签包含匹配"),
        OpenApiParameter("keyword", str, description="关键词（名称/标签/路径/上传人）"),
        OpenApiParameter("upload_user", str, description="上传人"),
        OpenApiParameter("suffix", str, description="文件后缀，如 jpg"),
        OpenApiParameter("upload_time_from", str, description="上传时间起（ISO 8601）"),
        OpenApiParameter("upload_time_to", str, description="上传时间止（ISO 8601）"),
        OpenApiParameter("include_deleted", str, description="1 包含已逻辑删除（普通用户仅自己的）"),
    ],
)
class ImageListView(APIView):
    """GET /api/images/ — paginated image list with filters."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        try:
            queryset = filter_image_queryset(request, is_admin=_is_admin(request.user))
            page_data = paginate_queryset(request, queryset)
        except ValueError as exc:
            return error_response(str(exc), code=4001, status=400)

        page_data["results"] = ImageInfoSerializer(page_data["results"], many=True).data
        return success_response(page_data)


@extend_schema(tags=["images"])
class ImageDetailView(APIView):
    """GET/PATCH/DELETE /api/images/{id}/ — detail, update metadata, logical delete."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request, pk: int):
        image = _get_active_image(pk)
        if image is None:
            return error_response("图片不存在或已删除", code=4041, status=404)
        return success_response(ImageInfoSerializer(image).data)

    def patch(self, request, pk: int):
        image = _get_active_image(pk)
        if image is None:
            return error_response("图片不存在或已删除", code=4041, status=404)

        serializer = ImageInfoUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)

        data = serializer.validated_data
        try:
            if "category_id" in data:
                validate_category_id(data["category_id"])
        except ValueError as exc:
            return error_response(str(exc), code=4001, status=400)

        for field, value in data.items():
            setattr(image, field, value)
        image.save(update_fields=list(data.keys()))

        write_operate_log(
            request,
            "image_update",
            detail=f"image_id={pk} fields={','.join(data.keys())}",
        )
        return success_response(ImageInfoSerializer(image).data, message="更新成功")

    def delete(self, request, pk: int):
        image = _get_active_image(pk)
        if image is None:
            return error_response("图片不存在或已删除", code=4041, status=404)

        payload = _logical_delete_image(image)
        write_operate_log(
            request,
            "image_delete",
            detail=f"image_id={pk} path={image.image_path} purge_at={payload['deletion_info']['purge_at']}",
        )
        return success_response(payload, message="图片已逻辑删除")


@extend_schema(tags=["images"], request=ImageBatchDeleteSerializer)
class ImageBatchDeleteView(APIView):
    """POST /api/images/batch-delete/ — batch logical delete."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request):
        serializer = ImageBatchDeleteSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)

        result = batch_logical_delete(serializer.validated_data["ids"])
        data = serialize_batch_delete_result(result)

        write_operate_log(
            request,
            "image_batch_delete",
            detail=(
                f"total={result.total} ok={result.succeeded} fail={result.failed} "
                f"ids={','.join(str(i) for i in serializer.validated_data['ids'][:20])}"
            ),
        )

        if result.succeeded == 0:
            return error_response(
                "批量删除失败",
                code=4002,
                data=data,
                status=400,
            )

        message = f"批量删除完成：成功 {result.succeeded}，失败 {result.failed}"
        return success_response(data, message=message)


@extend_schema(tags=["images"])
class ImageRestoreView(APIView):
    """POST /api/images/{id}/restore/ — restore a logically deleted image."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def post(self, request, pk: int):
        try:
            image = restore_image(pk=pk, user=request.user)
        except RestoreError as exc:
            return error_response(str(exc), code=4007, status=400)

        write_operate_log(
            request,
            "image_restore",
            detail=f"image_id={pk} path={image.image_path}",
        )
        return success_response(ImageInfoSerializer(image).data, message="图片已恢复")
