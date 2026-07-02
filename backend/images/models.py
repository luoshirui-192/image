from django.db import models


class ImageCategory(models.Model):
    category_name = models.CharField(max_length=100, default="")
    sort = models.IntegerField(default=0)
    create_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "image_category"
        verbose_name = "图片分类"
        verbose_name_plural = "图片分类"
        ordering = ["sort", "id"]
        indexes = [
            models.Index(fields=["sort"], name="idx_sort"),
        ]

    def __str__(self) -> str:
        return self.category_name


class ImageInfo(models.Model):
    image_name = models.CharField(max_length=255, default="")
    image_path = models.CharField(max_length=500, default="")
    image_width = models.IntegerField(default=0)
    image_height = models.IntegerField(default=0)
    file_size = models.PositiveBigIntegerField(default=0)
    file_suffix = models.CharField(max_length=20, default="")
    file_hash = models.CharField(max_length=64, default="")
    upload_time = models.DateTimeField()
    update_time = models.DateTimeField()
    upload_user = models.CharField(max_length=100, default="")
    is_delete = models.SmallIntegerField(default=0)
    category_id = models.PositiveIntegerField(null=True, blank=True)
    tags = models.CharField(max_length=500, default="")

    class Meta:
        managed = False
        db_table = "image_info"
        verbose_name = "图片信息"
        verbose_name_plural = "图片信息"
        ordering = ["-upload_time", "-id"]
        indexes = [
            models.Index(fields=["upload_time"], name="idx_upload_time"),
            models.Index(fields=["upload_user"], name="idx_upload_user"),
            models.Index(fields=["image_name"], name="idx_image_name"),
            models.Index(fields=["file_hash"], name="idx_file_hash"),
            models.Index(fields=["is_delete", "upload_time"], name="idx_list_active"),
            models.Index(fields=["is_delete", "category_id", "upload_time"], name="idx_list_category"),
        ]

    def __str__(self) -> str:
        return self.image_name or self.image_path
