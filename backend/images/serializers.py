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


class ImageInfoUpdateSerializer(serializers.Serializer):
    image_name = serializers.CharField(max_length=255, required=False, allow_blank=False, trim_whitespace=True)
    category_id = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    tags = serializers.CharField(required=False, allow_blank=True, max_length=500, trim_whitespace=True)


class ImageImportSerializer(serializers.Serializer):
    directory = serializers.CharField(max_length=500, trim_whitespace=True)
    category_id = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    tags = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    recursive = serializers.BooleanField(required=False, default=False)


class ImageBatchDeleteSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=200,
        allow_empty=False,
    )
