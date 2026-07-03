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


class BlobMigrationSource(models.Model):
    name = models.CharField(max_length=100, default="")
    source_table = models.CharField(max_length=64)
    source_pk_column = models.CharField(max_length=64, default="id")
    blob_column = models.CharField(max_length=64)
    name_column = models.CharField(max_length=64, default="")
    suffix_column = models.CharField(max_length=64, default="")
    category_id = models.PositiveIntegerField()
    upload_user = models.CharField(max_length=100, default="migration")
    tags = models.CharField(max_length=500, default="")
    where_clause = models.CharField(max_length=500, default="")
    db_alias = models.CharField(max_length=32, default="default")
    enabled = models.SmallIntegerField(default=1)
    last_run_at = models.DateTimeField(null=True, blank=True)
    create_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "blob_migration_source"
        verbose_name = "BLOB 迁移源"
        verbose_name_plural = "BLOB 迁移源"
        ordering = ["-id"]

    def __str__(self) -> str:
        return self.name or f"{self.source_table}.{self.blob_column}"


class ImageSourceMap(models.Model):
    source_table = models.CharField(max_length=64)
    source_id = models.CharField(max_length=64)
    image_info_id = models.PositiveBigIntegerField()
    migrated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "image_source_map"
        verbose_name = "图像源映射"
        verbose_name_plural = "图像源映射"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["source_table", "source_id"], name="uk_source"),
            models.Index(fields=["image_info_id"], name="idx_image_info"),
        ]

    def __str__(self) -> str:
        return f"{self.source_table}:{self.source_id} -> {self.image_info_id}"


class BlobTableView(models.Model):
    name = models.CharField(max_length=100, default="")
    db_alias = models.CharField(max_length=32, default="default")
    source_table = models.CharField(max_length=64)
    source_pk_column = models.CharField(max_length=64, default="id")
    blob_column = models.CharField(max_length=64)
    display_columns = models.TextField(default="")
    where_clause = models.CharField(max_length=500, default="")
    remark = models.CharField(max_length=500, default="")
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    create_time = models.DateTimeField(null=True, blank=True)
    update_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "blob_table_view"
        verbose_name = "BLOB 表视图"
        verbose_name_plural = "BLOB 表视图"
        ordering = ["-id"]

    def __str__(self) -> str:
        return self.name or f"{self.source_table}.{self.blob_column}"


class ExternalDbConnection(models.Model):
    name = models.CharField(max_length=100, default="")
    host = models.CharField(max_length=255, default="")
    port = models.PositiveIntegerField(default=3306)
    db_name = models.CharField(max_length=64, default="")
    username = models.CharField(max_length=100, default="")
    password_encrypted = models.TextField(default="")
    charset = models.CharField(max_length=16, default="utf8")
    remark = models.CharField(max_length=500, default="")
    enabled = models.SmallIntegerField(default=1)
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.SmallIntegerField(default=0)
    last_test_message = models.CharField(max_length=500, default="")
    create_time = models.DateTimeField(null=True, blank=True)
    update_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "external_db_connection"
        verbose_name = "外部数据库连接"
        verbose_name_plural = "外部数据库连接"
        ordering = ["-id"]

    def __str__(self) -> str:
        return self.name or f"{self.username}@{self.host}/{self.db_name}"
