"""Image file serving API — Step 14."""
from __future__ import annotations

from django.http import FileResponse, HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from images.file_service import (
    ImageNotFoundError,
    ImageResolveError,
    build_access_token,
    content_type_for_path,
    ensure_access_allowed,
    get_absolute_image_path,
    get_or_create_thumbnail,
    read_image_bytes,
    resolve_image_location,
)
from utils.storage import get_image_storage
from utils.file_security import AccessDeniedError, PathSecurityError
from utils.permissions import IsActiveAccount
from utils.responses import error_response, success_response


def _parse_optional_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ImageResolveError("id 必须为整数") from None


def _query_params(request) -> tuple[str | None, int | None, str | None]:
    path = request.query_params.get("path")
    token = request.query_params.get("token")
    image_id = _parse_optional_int(request.query_params.get("id"))
    return path, image_id, token


def _is_authenticated_user(request) -> bool:
    user = request.user
    return bool(user and getattr(user, "is_authenticated", False) and getattr(user, "status", 1) == 1)


def _serve_file(abs_path, filename: str, *, as_attachment: bool, content_type: str) -> FileResponse:
    response = FileResponse(abs_path.open("rb"), content_type=content_type)
    if as_attachment:
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
    else:
        response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def _serve_bytes(data: bytes, filename: str, *, as_attachment: bool, content_type: str) -> HttpResponse:
    disposition = "attachment" if as_attachment else "inline"
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response


class _BaseImageServeView(APIView):
    """Shared auth + path resolution for image streaming endpoints."""

    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]

    as_attachment = False
    use_thumbnail = False

    def get(self, request):
        try:
            path, image_id, token = _query_params(request)
            relative_path, filename = resolve_image_location(path=path, image_id=image_id)
            ensure_access_allowed(
                relative_path,
                is_authenticated=_is_authenticated_user(request),
                access_token=token,
            )

            if self.use_thumbnail:
                abs_path = get_or_create_thumbnail(relative_path)
                content_type = "image/jpeg"
                serve_name = f"thumb_{filename.rsplit('.', 1)[0]}.jpg"
                return _serve_file(
                    abs_path,
                    serve_name,
                    as_attachment=self.as_attachment,
                    content_type=content_type,
                )

            content_type = content_type_for_path(relative_path)
            serve_name = filename
            storage = get_image_storage()
            if storage.backend_name == "local":
                abs_path = get_absolute_image_path(relative_path)
                return _serve_file(
                    abs_path,
                    serve_name,
                    as_attachment=self.as_attachment,
                    content_type=content_type,
                )

            data = read_image_bytes(relative_path)
            return _serve_bytes(
                data,
                serve_name,
                as_attachment=self.as_attachment,
                content_type=content_type,
            )
        except ImageResolveError as exc:
            return error_response(str(exc), code=4001, status=400)
        except ImageNotFoundError as exc:
            return error_response(str(exc), code=4041, status=404)
        except PathSecurityError as exc:
            return error_response(str(exc), code=4003, status=403)
        except AccessDeniedError as exc:
            return error_response(str(exc), code=4001, status=403)


@extend_schema(
    tags=["images"],
    parameters=[
        OpenApiParameter("path", OpenApiTypes.STR, description="图片相对路径，如 upload/20260630/1/uuid.jpg"),
        OpenApiParameter("id", OpenApiTypes.INT, description="图片 ID（与 path 二选一）"),
        OpenApiParameter("token", OpenApiTypes.STR, description="匿名访问令牌（未登录时必填）"),
    ],
    responses={(200, "image/*"): bytes},
)
class ImageFileView(_BaseImageServeView):
    """GET /api/images/file/ — stream original image."""

    as_attachment = False
    use_thumbnail = False


@extend_schema(
    tags=["images"],
    parameters=[
        OpenApiParameter("path", OpenApiTypes.STR, description="图片相对路径"),
        OpenApiParameter("id", OpenApiTypes.INT, description="图片 ID"),
        OpenApiParameter("token", OpenApiTypes.STR, description="匿名访问令牌"),
    ],
    responses={(200, "image/jpeg"): bytes},
)
class ImageThumbView(_BaseImageServeView):
    """GET /api/images/thumb/ — cached thumbnail (first access generates)."""

    use_thumbnail = True


@extend_schema(
    tags=["images"],
    parameters=[
        OpenApiParameter("path", OpenApiTypes.STR, description="图片相对路径"),
        OpenApiParameter("id", OpenApiTypes.INT, description="图片 ID"),
        OpenApiParameter("token", OpenApiTypes.STR, description="匿名访问令牌"),
    ],
    responses={(200, "application/octet-stream"): bytes},
)
class ImageDownloadView(_BaseImageServeView):
    """GET /api/images/download/ — download original image as attachment."""

    as_attachment = True
    use_thumbnail = False


@extend_schema(
    tags=["images"],
    parameters=[
        OpenApiParameter("path", OpenApiTypes.STR, required=True, description="图片相对路径"),
    ],
)
class ImageAccessTokenView(APIView):
    """GET /api/images/access-token/ — issue short-lived token for img src URLs."""

    permission_classes = [IsAuthenticated, IsActiveAccount]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        path = request.query_params.get("path")
        if not path:
            return error_response("请提供 path 参数", code=4001, status=400)

        try:
            data = build_access_token(path)
        except PathSecurityError as exc:
            return error_response(str(exc), code=4003, status=403)
        except ValueError as exc:
            return error_response(str(exc), code=4001, status=400)

        return success_response(data, message="访问令牌已生成")
