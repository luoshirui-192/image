from django.contrib import admin

from logs.models import OperateLog


@admin.register(OperateLog)
class OperateLogAdmin(admin.ModelAdmin):
    list_display = ("id", "username", "action_type", "create_time", "ip")
    list_filter = ("action_type",)
    search_fields = ("username", "detail", "sql_content")
