"""SQL query serializers — Step 13."""
from __future__ import annotations

from rest_framework import serializers


class SqlExecuteSerializer(serializers.Serializer):
    sql = serializers.CharField(max_length=10000, trim_whitespace=False, allow_blank=False)


class SqlTemplateCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, trim_whitespace=True)
    sql = serializers.CharField(max_length=10000, trim_whitespace=False)
