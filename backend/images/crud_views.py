"""Image detail/update/delete API — Step 15."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from images.models import ImageInfo
from images.permissions import can_modify_image, is_admin
from images.purge_service import purge_image_record
from images.querysets import validate_category_id
from images.restore_service import RestoreError, restore_image
from images.serializers import ImageInfoUpdateSerializer, serialize_image_info
from utils.audit import write_operate_log
from utils.permissions import IsActiveAccount
from utils.responses import error_response, success_response

PERMANENT_DELETE_NOTICE = "已永久删除磁盘文件、数据库记录及 BLOB 迁移映射，不可恢复。"


def _format_errors(errors: dict) -> str:
    if not errors:
        return "请求参数错误"
    parts = []
    for key, val in errors.items():
        msg = val[0] if isinstance(val, list) else val
        parts.append(f"{key}: {msg}")
    return "; ".join(parts)


def _get_active_image(pk: int) -> ImageInfo | None:
    try:
        return ImageInfo.objects.get(pk=pk, is_delete=0)
    except ImageInfo.DoesNotExist:
        return None


@extend_schema(tags=["images"])
class ImageDetailView(APIView):
    """GET/PATCH/DELETE /api/images/{id}/ — detail, update metadata, permanent delete."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request, pk: int):
        image = _get_active_image(pk)
        if image is None:
            return error_response("图片不存在或已删除", code=4041, status=404)
        return success_response(serialize_image_info(image, is_admin=is_admin(request.user)))

    def patch(self, request, pk: int):
        image = _get_active_image(pk)
        if image is None:
            return error_response("图片不存在或已删除", code=4041, status=404)
        if not can_modify_image(request.user, image):
            return error_response("无权编辑他人上传的图片", code=4031, status=403)

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
        return success_response(
            serialize_image_info(image, is_admin=is_admin(request.user)),
            message="更新成功",
        )

    def delete(self, request, pk: int):
        image = _get_active_image(pk)
        if image is None:
            return error_response("图片不存在或已删除", code=4041, status=404)
        if not can_modify_image(request.user, image):
            return error_response("无权删除他人上传的图片", code=4031, status=403)

        image_path = image.image_path
        image_name = image.image_name
        purge_result = purge_image_record(image)
        write_operate_log(
            request,
            "image_delete",
            detail=(
                f"image_id={pk} path={image_path} "
                f"maps_removed={purge_result.source_maps_deleted} permanent=1"
            ),
        )
        return success_response(
            {
                "image_name": image_name,
                "image_path": image_path,
                "permanent": True,
                "notice": PERMANENT_DELETE_NOTICE,
            },
            message="图片已永久删除",
        )


@extend_schema(tags=["images"])
class ImageRestoreView(APIView):
    """POST /api/images/{id}/restore/ — restore legacy logically deleted images only."""

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
        return success_response(
            serialize_image_info(image, is_admin=is_admin(request.user)),
            message="图片已恢复",
        )
