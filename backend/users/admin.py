from django.contrib import admin

from users.models import SysUser


@admin.register(SysUser)
class SysUserAdmin(admin.ModelAdmin):
    list_display = ("id", "username", "role", "status", "create_time")
    search_fields = ("username",)
    list_filter = ("role", "status")
