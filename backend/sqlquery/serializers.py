"""SQL query serializers — Step 13 + PR3 browse context."""
from __future__ import annotations

from rest_framework import serializers


class SqlExecuteSerializer(serializers.Serializer):
    sql = serializers.CharField(max_length=10000, trim_whitespace=False, allow_blank=False)
    db_alias = serializers.CharField(required=False, allow_blank=True, default="", max_length=32)
    connection_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    database = serializers.CharField(required=False, allow_blank=True, default="", max_length=64)


class SqlTemplateCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, trim_whitespace=True)
    sql = serializers.CharField(max_length=10000, trim_whitespace=False)
