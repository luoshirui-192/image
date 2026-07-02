"""Auth serializers."""
from __future__ import annotations

from rest_framework import serializers

from users.models import SysUser


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=100, trim_whitespace=True)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        username = attrs["username"]
        password = attrs["password"]

        try:
            user = SysUser.objects.get(username=username)
        except SysUser.DoesNotExist:
            raise serializers.ValidationError("用户名或密码错误") from None
        except Exception as exc:
            from django.db import DatabaseError

            if isinstance(exc, DatabaseError):
                raise serializers.ValidationError(
                    "数据库未就绪：请使用 MySQL（.env 中 DB_ENGINE=mysql），"
                    "并导入 sql/image_db.sql 与 sql/seed_test_data.sql"
                ) from None
            raise

        if not user.check_password(password):
            raise serializers.ValidationError("用户名或密码错误")

        if user.status != 1:
            raise serializers.ValidationError("账号已禁用")

        attrs["user"] = user
        return attrs


class UserSerializer(serializers.ModelSerializer):
    is_admin = serializers.SerializerMethodField()

    class Meta:
        model = SysUser
        fields = ("id", "username", "role", "status", "is_admin", "create_time")
        read_only_fields = fields

    def get_is_admin(self, obj: SysUser) -> bool:
        return obj.role == "admin"
