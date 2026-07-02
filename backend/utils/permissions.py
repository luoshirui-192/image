"""Custom permissions."""
from rest_framework.permissions import BasePermission


class IsActiveAccount(BasePermission):
    """Reject disabled accounts (sys_user.status != 1)."""

    message = "账号已禁用"

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and getattr(user, "status", 0) == 1)


class IsAdminRole(BasePermission):
    """Allow only users with role=admin."""

    message = "需要管理员权限"

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "status", 0) == 1
            and getattr(user, "role", "") == "admin"
        )
