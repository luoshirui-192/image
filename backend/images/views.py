"""Image upload, import, and category API — Step 12."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from django.utils import timezone

from images.models import ImageCategory, ImageInfo
from images.serializers import ImageCategorySerializer, ImageImportSerializer, ImageInfoSerializer, serialize_image_info
from images.services import (
    DuplicateBatchError,
    import_images_from_directory,
    save_uploaded_files,
)
from utils.audit import write_operate_log
from utils.permissions import IsActiveAccount, IsAdminRole
from utils.responses import error_response, success_response


def _serialize_upload_results(results, *, is_admin: bool = True):
    items = []
    for item in results:
        entry = {"filename": item.filename, "success": item.success}
        if item.success and item.image:
            entry["image"] = serialize_image_info(item.image, is_admin=is_admin)
            entry["overwritten"] = item.overwritten
        elif item.error:
            entry["error"] = item.error
        if item.duplicate and item.existing_image:
            entry["duplicate"] = True
            entry["existing"] = serialize_image_info(item.existing_image, is_admin=is_admin)
        items.append(entry)
    return items


def _serialize_duplicates(duplicates: list[dict], *, is_admin: bool = True):
    items = []
    for item in duplicates:
        entry = {"filename": item["filename"]}
        if item.get("existing") is not None:
            entry["existing"] = serialize_image_info(item["existing"], is_admin=is_admin)
        if item.get("batch_duplicate_of"):
            entry["batch_duplicate_of"] = item["batch_duplicate_of"]
        items.append(entry)
    return items


def _parse_overwrite_param(value) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).lower() in {"1", "true", "yes", "on"}


def _upload_summary(results):
    succeeded = sum(1 for r in results if r.success)
    failed = len(results) - succeeded
    return {"total": len(results), "succeeded": succeeded, "failed": failed}


@extend_schema(
    tags=["images"],
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary"},
                "files": {"type": "array", "items": {"type": "string", "format": "binary"}},
                "category_id": {"type": "integer"},
                "tags": {"type": "string"},
            },
        }
    },
)
class ImageUploadView(APIView):
    """POST /api/images/upload/ — single or multi-file upload."""

    permission_classes = [IsAuthenticated, IsActiveAccount]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        files = list(request.FILES.getlist("files"))
        if not files and request.FILES.get("file"):
            files = [request.FILES["file"]]

        if not files:
            return error_response("请至少上传一个图片文件", code=4001, status=400)

        category_id = request.data.get("category_id")
        if category_id in ("", None):
            return error_response("上传时必须选择分类", code=4001, status=400)
        try:
            parsed_category_id = int(category_id)
        except (TypeError, ValueError):
            return error_response("category_id 必须为整数", code=4001, status=400)
        if parsed_category_id <= 0:
            return error_response("必须选择有效分类", code=4001, status=400)

        tags = str(request.data.get("tags", ""))
        overwrite = _parse_overwrite_param(request.data.get("overwrite"))
        admin = getattr(request.user, "role", "") == "admin"

        try:
            results = save_uploaded_files(
                files,
                upload_user=request.user.username,
                category_id=parsed_category_id,
                tags=tags,
                overwrite=overwrite,
            )
        except DuplicateBatchError as exc:
            dupes = _serialize_duplicates(exc.duplicates, is_admin=admin)
            return error_response(
                "存在重复图片，请确认是否覆盖原有数据",
                code=4006,
                data={"duplicates": dupes},
                status=409,
            )
        except ValueError as exc:
            return error_response(str(exc), code=4001, status=400)

        summary = _upload_summary(results)
        write_operate_log(
            request,
            "upload",
            detail=f"upload files total={summary['total']} ok={summary['succeeded']} fail={summary['failed']}",
        )

        if summary["succeeded"] == 0:
            return error_response(
                "全部文件上传失败",
                code=4002,
                data={"summary": summary, "items": _serialize_upload_results(results, is_admin=admin)},
                status=400,
            )

        return success_response(
            {"summary": summary, "items": _serialize_upload_results(results, is_admin=admin)},
            message=f"上传完成：成功 {summary['succeeded']}，失败 {summary['failed']}",
        )


@extend_schema(tags=["images"], request=ImageImportSerializer)
class ImageImportView(APIView):
    """POST /api/images/import/ — batch import from server-local directory (admin)."""

    permission_classes = [IsAuthenticated, IsActiveAccount, IsAdminRole]

    def post(self, request):
        serializer = ImageImportSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                _format_errors(serializer.errors),
                code=4001,
                status=400,
            )

        data = serializer.validated_data
        overwrite = _parse_overwrite_param(request.data.get("overwrite"))
        try:
            results = import_images_from_directory(
                data["directory"],
                upload_user=request.user.username,
                category_id=data.get("category_id"),
                tags=data.get("tags", ""),
                recursive=data.get("recursive", False),
                overwrite=overwrite,
            )
        except DuplicateBatchError as exc:
            dupes = _serialize_duplicates(exc.duplicates, is_admin=True)
            return error_response(
                "存在重复图片，请确认是否覆盖原有数据",
                code=4006,
                data={"duplicates": dupes},
                status=409,
            )
        except ValueError as exc:
            return error_response(str(exc), code=4001, status=400)

        summary = _upload_summary(results)
        write_operate_log(
            request,
            "import",
            detail=(
                f"import dir={data['directory']} total={summary['total']} "
                f"ok={summary['succeeded']} fail={summary['failed']}"
            ),
        )

        if summary["total"] == 0:
            return error_response("目录中未找到可导入的图片文件", code=4004, status=400)

        return success_response(
            {"summary": summary, "items": _serialize_upload_results(results, is_admin=True)},
            message=f"导入完成：成功 {summary['succeeded']}，失败 {summary['failed']}",
        )


@extend_schema(tags=["categories"])
class CategoryListCreateView(APIView):
    """GET/POST /api/images/categories/ — list or create categories."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get_permissions(self):
        return [IsAuthenticated(), IsActiveAccount()]

    def get(self, request):
        qs = ImageCategory.objects.all().order_by("sort", "id")
        return success_response(ImageCategorySerializer(qs, many=True).data)

    def post(self, request):
        serializer = ImageCategorySerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)

        category = serializer.save(create_time=timezone.now())
        write_operate_log(request, "category_create", detail=f"category={category.category_name}")
        return success_response(ImageCategorySerializer(category).data, message="分类创建成功", status=201)


@extend_schema(tags=["categories"])
class CategoryDetailView(APIView):
    """GET/PATCH/DELETE /api/images/categories/{id}/."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get_permissions(self):
        if self.request.method in ("PATCH", "DELETE"):
            return [IsAuthenticated(), IsActiveAccount(), IsAdminRole()]
        return [IsAuthenticated(), IsActiveAccount()]

    def _get_category(self, pk: int):
        try:
            return ImageCategory.objects.get(pk=pk)
        except ImageCategory.DoesNotExist:
            return None

    def get(self, request, pk: int):
        category = self._get_category(pk)
        if category is None:
            return error_response("分类不存在", code=4044, status=404)
        return success_response(ImageCategorySerializer(category).data)

    def patch(self, request, pk: int):
        category = self._get_category(pk)
        if category is None:
            return error_response("分类不存在", code=4044, status=404)

        serializer = ImageCategorySerializer(category, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response(_format_errors(serializer.errors), code=4001, status=400)

        updated = serializer.save()
        write_operate_log(request, "category_update", detail=f"category_id={pk}")
        return success_response(ImageCategorySerializer(updated).data, message="分类更新成功")

    def delete(self, request, pk: int):
        category = self._get_category(pk)
        if category is None:
            return error_response("分类不存在", code=4044, status=404)

        if ImageInfo.objects.filter(category_id=pk, is_delete=0).exists():
            return error_response("分类下仍有图片，无法删除", code=4005, status=400)

        name = category.category_name
        category.delete()
        write_operate_log(request, "category_delete", detail=f"category={name}")
        return success_response(None, message="分类删除成功")


def _format_errors(errors: dict) -> str:
    if not errors:
        return "请求参数错误"
    parts = []
    for key, val in errors.items():
        msg = val[0] if isinstance(val, list) else val
        parts.append(f"{key}: {msg}")
    return "; ".join(parts)
