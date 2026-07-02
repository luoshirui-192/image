from django.contrib import admin

from images.models import ImageCategory, ImageInfo


@admin.register(ImageCategory)
class ImageCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "category_name", "sort", "create_time")


@admin.register(ImageInfo)
class ImageInfoAdmin(admin.ModelAdmin):
    list_display = ("id", "image_name", "image_path", "category_id", "is_delete", "upload_time")
    list_filter = ("is_delete", "file_suffix")
    search_fields = ("image_name", "image_path", "tags")
