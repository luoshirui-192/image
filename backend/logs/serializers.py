from rest_framework import serializers

from logs.models import OperateLog


class OperateLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperateLog
        fields = (
            "id",
            "user_id",
            "username",
            "action_type",
            "sql_content",
            "detail",
            "ip",
            "create_time",
        )
