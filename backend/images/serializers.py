"""Image and category serializers — Step 12."""
from __future__ import annotations

from rest_framework import serializers

from images.deletion_policy import build_deletion_info
from images.models import ImageCategory, ImageInfo


class ImageCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ImageCategory
        fields = ("id", "category_name", "sort", "create_time")
        read_only_fields = ("id", "create_time")


class ImageInfoSerializer(serializers.ModelSerializer):
    deletion_info = serializers.SerializerMethodField()

    class Meta:
        model = ImageInfo
        fields = (
            "id",
            "image_name",
            "image_path",
            "image_width",
            "image_height",
            "file_size",
            "file_suffix",
            "upload_time",
            "update_time",
            "upload_user",
            "is_delete",
            "category_id",
            "tags",
            "deletion_info",
        )
        read_only_fields = fields

    def get_deletion_info(self, obj: ImageInfo):
        if not obj.is_delete:
            return None
        return build_deletion_info(obj.update_time)


class ImageInfoClientSerializer(serializers.ModelSerializer):
    """Client-facing list/detail — hides server storage paths."""

    deletion_info = serializers.SerializerMethodField()

    class Meta:
        model = ImageInfo
        fields = (
            "id",
            "image_name",
            "image_width",
            "image_height",
            "file_size",
            "file_suffix",
            "upload_time",
            "update_time",
            "upload_user",
            "is_delete",
            "category_id",
            "tags",
            "deletion_info",
        )
        read_only_fields = fields

    def get_deletion_info(self, obj: ImageInfo):
        if not obj.is_delete:
            return None
        return build_deletion_info(obj.update_time)


def serialize_image_info(image: ImageInfo, *, is_admin: bool) -> dict:
    if is_admin:
        return ImageInfoSerializer(image).data
    return ImageInfoClientSerializer(image).data


class ImageInfoUpdateSerializer(serializers.Serializer):
    image_name = serializers.CharField(max_length=255, required=False, allow_blank=False, trim_whitespace=True)
    category_id = serializers.IntegerField(required=False, allow_null=False, min_value=1)
    tags = serializers.CharField(required=False, allow_blank=True, max_length=500, trim_whitespace=True)


class BlobMigrationDiscoverSerializer(serializers.Serializer):
    db_alias = serializers.CharField(required=False, default="default", max_length=32)


class BlobMigrationSourceSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(required=False, allow_blank=True, max_length=100, default="")
    source_table = serializers.CharField(max_length=64, trim_whitespace=True)
    source_pk_column = serializers.CharField(required=False, default="id", max_length=64, trim_whitespace=True)
    blob_column = serializers.CharField(required=False, max_length=64, trim_whitespace=True, allow_blank=True)
    blob_columns = serializers.ListField(
        child=serializers.CharField(max_length=64, trim_whitespace=True),
        required=False,
        allow_empty=False,
    )
    source_object_type = serializers.ChoiceField(
        choices=["table", "view"],
        required=False,
        default="table",
    )
    path_lookup_table = serializers.CharField(required=False, allow_blank=True, default="", max_length=64)
    name_column = serializers.CharField(required=False, allow_blank=True, default="", max_length=64)
    suffix_column = serializers.CharField(required=False, allow_blank=True, default="", max_length=64)
    category_id = serializers.IntegerField(min_value=1)
    upload_user = serializers.CharField(required=False, allow_blank=True, default="migration", max_length=100)
    tags = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    where_clause = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    db_alias = serializers.CharField(required=False, default="default", max_length=32)
    enabled = serializers.IntegerField(required=False, default=1)
    last_run_at = serializers.DateTimeField(read_only=True)
    create_time = serializers.DateTimeField(read_only=True)

    def validate(self, attrs):
        blob_column = (attrs.get("blob_column") or "").strip()
        blob_columns = attrs.get("blob_columns") or []
        if not blob_column and not blob_columns:
            raise serializers.ValidationError("请提供 blob_column 或 blob_columns")
        if blob_column and not blob_columns:
            attrs["blob_column"] = blob_column
        elif blob_columns and not blob_column:
            attrs["blob_column"] = blob_columns[0]
        return attrs

    def to_representation(self, instance):
        from images.blob_schema_helpers import parse_blob_columns
        from images.models import BlobMigrationSource

        if isinstance(instance, BlobMigrationSource):
            return {
                "id": instance.id,
                "name": instance.name,
                "source_table": instance.source_table,
                "source_pk_column": instance.source_pk_column,
                "blob_column": instance.blob_column,
                "blob_columns": parse_blob_columns(instance.blob_columns, instance.blob_column),
                "source_object_type": instance.source_object_type or "table",
                "path_lookup_table": instance.path_lookup_table or "",
                "name_column": instance.name_column,
                "suffix_column": instance.suffix_column,
                "category_id": instance.category_id,
                "upload_user": instance.upload_user,
                "tags": instance.tags,
                "where_clause": instance.where_clause,
                "db_alias": instance.db_alias,
                "enabled": instance.enabled,
                "last_run_at": instance.last_run_at,
                "create_time": instance.create_time,
            }
        return super().to_representation(instance)


class BlobMigrationRunSerializer(serializers.Serializer):
    source_id = serializers.IntegerField(min_value=1)
    batch_size = serializers.IntegerField(required=False, default=50, min_value=1, max_value=500)
    dry_run = serializers.BooleanField(required=False, default=False)
    skip_existing = serializers.BooleanField(required=False, default=True)


class BlobMigrationJobCreateSerializer(serializers.Serializer):
    source_id = serializers.IntegerField(min_value=1)
    batch_size = serializers.IntegerField(required=False, default=50, min_value=1, max_value=500)
    dry_run = serializers.BooleanField(required=False, default=False)
    skip_existing = serializers.BooleanField(required=False, default=True)
    run_all = serializers.BooleanField(required=False, default=True)
    warm_thumbs_after = serializers.BooleanField(required=False, default=False)


class BlobMigrationJobRetrySerializer(serializers.Serializer):
    parent_job_id = serializers.IntegerField(min_value=1)
    batch_size = serializers.IntegerField(required=False, default=50, min_value=1, max_value=500)
    dry_run = serializers.BooleanField(required=False, default=False)
    warm_thumbs_after = serializers.BooleanField(required=False, default=False)


class BlobMigrationJobClearSerializer(serializers.Serializer):
    source_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class ExternalDbConnectionSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=100, trim_whitespace=True)
    host = serializers.CharField(max_length=255, trim_whitespace=True)
    port = serializers.IntegerField(min_value=1, max_value=65535, default=3306)
    db_name = serializers.CharField(max_length=64, trim_whitespace=True)
    username = serializers.CharField(max_length=100, trim_whitespace=True)
    password = serializers.CharField(max_length=255, write_only=True, required=False, allow_blank=True)
    charset = serializers.CharField(required=False, default="utf8", max_length=16)
    remark = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    enabled = serializers.IntegerField(required=False, default=1)


class ExternalDbConnectionTestSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, default="test", max_length=100)
    host = serializers.CharField(max_length=255, trim_whitespace=True)
    port = serializers.IntegerField(min_value=1, max_value=65535, default=3306)
    db_name = serializers.CharField(max_length=64, trim_whitespace=True)
    username = serializers.CharField(max_length=100, trim_whitespace=True)
    password = serializers.CharField(max_length=255, write_only=True)
    charset = serializers.CharField(required=False, default="utf8", max_length=16)


class BlobTableViewSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=100)
    db_alias = serializers.CharField(max_length=32)
    database_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=64)
    source_table = serializers.CharField(max_length=64)
    source_object_type = serializers.ChoiceField(choices=["table", "view"], required=False, default="table")
    path_lookup_table = serializers.CharField(required=False, allow_blank=True, default="", max_length=64)
    source_pk_column = serializers.CharField(max_length=64)
    blob_column = serializers.CharField(max_length=64)
    blob_columns = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
    )
    display_columns = serializers.CharField(required=False, allow_blank=True, default="")
    where_clause = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    remark = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    last_viewed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    create_time = serializers.DateTimeField(read_only=True, allow_null=True)
    update_time = serializers.DateTimeField(read_only=True, allow_null=True)

    def to_representation(self, instance):
        from images.blob_schema_helpers import parse_blob_column_path_mappings, parse_blob_columns
        from images.models import BlobTableView

        if isinstance(instance, BlobTableView):
            return {
                "id": instance.id,
                "name": instance.name,
                "db_alias": instance.db_alias,
                "database_name": instance.database_name or "",
                "source_table": instance.source_table,
                "source_object_type": instance.source_object_type or "table",
                "path_lookup_table": instance.path_lookup_table or "",
                "blob_column_path_mappings": parse_blob_column_path_mappings(
                    instance.blob_column_path_mappings
                ),
                "source_pk_column": instance.source_pk_column,
                "blob_column": instance.blob_column,
                "blob_columns": parse_blob_columns(instance.blob_columns, instance.blob_column),
                "display_columns": instance.display_columns,
                "where_clause": instance.where_clause,
                "remark": instance.remark,
                "last_viewed_at": instance.last_viewed_at,
                "create_time": instance.create_time,
                "update_time": instance.update_time,
            }
        return super().to_representation(instance)


class BlobTableViewCreateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    db_alias = serializers.CharField(required=False, default="default", max_length=32)
    database_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=64)
    source_table = serializers.CharField(max_length=64, trim_whitespace=True)
    source_object_type = serializers.ChoiceField(choices=["table", "view"], required=False, default="table")
    path_lookup_table = serializers.CharField(required=False, allow_blank=True, default="", max_length=64)
    source_pk_column = serializers.CharField(required=False, default="id", max_length=64, trim_whitespace=True)
    blob_column = serializers.CharField(required=False, max_length=64, trim_whitespace=True, allow_blank=True)
    blob_columns = serializers.ListField(
        child=serializers.CharField(max_length=64, trim_whitespace=True),
        required=False,
        allow_empty=False,
    )
    display_columns = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
    )
    where_clause = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    remark = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)

    def validate(self, attrs):
        blob_column = (attrs.get("blob_column") or "").strip()
        blob_columns = attrs.get("blob_columns") or []
        if not blob_column and not blob_columns:
            raise serializers.ValidationError("请提供 blob_column 或 blob_columns")
        if blob_column and not blob_columns:
            attrs["blob_column"] = blob_column
        elif blob_columns and not blob_column:
            attrs["blob_column"] = blob_columns[0]
        return attrs

    def to_representation(self, instance):
        from images.blob_schema_helpers import parse_blob_column_path_mappings, parse_blob_columns
        from images.models import BlobTableView

        if isinstance(instance, BlobTableView):
            return {
                "id": instance.id,
                "name": instance.name,
                "db_alias": instance.db_alias,
                "database_name": instance.database_name or "",
                "source_table": instance.source_table,
                "source_object_type": instance.source_object_type or "table",
                "path_lookup_table": instance.path_lookup_table or "",
                "blob_column_path_mappings": parse_blob_column_path_mappings(
                    instance.blob_column_path_mappings
                ),
                "source_pk_column": instance.source_pk_column,
                "blob_column": instance.blob_column,
                "blob_columns": parse_blob_columns(instance.blob_columns, instance.blob_column),
                "display_columns": instance.display_columns,
                "where_clause": instance.where_clause,
                "remark": instance.remark,
                "last_viewed_at": instance.last_viewed_at,
                "create_time": instance.create_time,
                "update_time": instance.update_time,
            }
        return super().to_representation(instance)


class BlobTableViewUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    display_columns = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
    )
    where_clause = serializers.CharField(required=False, allow_blank=True, max_length=500)
    remark = serializers.CharField(required=False, allow_blank=True, max_length=500)


class BlobTableViewRowsSerializer(serializers.Serializer):
    offset = serializers.IntegerField(required=False, default=0, min_value=0)
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=500)


class BlobTableViewPreviewSchemaSerializer(serializers.Serializer):
    db_alias = serializers.CharField(required=False, default="default", max_length=32)
    source_table = serializers.CharField(max_length=64, trim_whitespace=True)
    source_pk_column = serializers.CharField(required=False, default="id", max_length=64, trim_whitespace=True)
    blob_column = serializers.CharField(max_length=64, trim_whitespace=True)
    display_columns = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
    )
