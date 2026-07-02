"""Auth API views — Step 11."""
from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView

from users.serializers import LoginSerializer, UserSerializer
from utils.audit import write_operate_log
from utils.permissions import IsActiveAccount
from utils.responses import error_response, success_response


@extend_schema(
    tags=["auth"],
    request=LoginSerializer,
    examples=[
        OpenApiExample(
            "管理员登录",
            value={"username": "admin", "password": "admin123"},
            request_only=True,
        ),
    ],
)
class LoginView(APIView):
    """POST /api/auth/login/ — JWT login."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            username = request.data.get("username", "")
            write_operate_log(
                request,
                "login",
                detail=f"login failed: {username}",
                username=str(username) if username else None,
            )
            return error_response(
                _format_errors(serializer.errors),
                code=4001,
                status=400,
            )

        user = serializer.validated_data["user"]
        refresh = RefreshToken.for_user(user)
        refresh["role"] = user.role
        refresh["username"] = user.username

        write_operate_log(request, "login", detail="login success", username=user.username, user_id=user.id)

        return success_response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            },
            message="登录成功",
        )


@extend_schema(tags=["auth"], responses={200: UserSerializer})
class MeView(APIView):
    """GET /api/auth/me/ — current user profile."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        return success_response(UserSerializer(request.user).data)


@extend_schema(tags=["auth"], request=TokenRefreshSerializer)
class TokenRefreshView(BaseTokenRefreshView):
    """POST /api/auth/refresh/ — refresh access token."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc

        return success_response(
            {"access": serializer.validated_data["access"]},
            message="令牌刷新成功",
        )


def _format_errors(errors: dict) -> str:
    if not errors:
        return "请求参数错误"
    if "non_field_errors" in errors:
        val = errors["non_field_errors"]
        return str(val[0] if isinstance(val, list) else val)
    parts = []
    for key, val in errors.items():
        msg = val[0] if isinstance(val, list) else val
        parts.append(f"{key}: {msg}")
    return "; ".join(parts)
