from django.apps import AppConfig


class ImagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "images"
    verbose_name = "图片与分类"

    def ready(self) -> None:
        from images.schema_ensure import ensure_file_hash_column, ensure_migration_tables

        ensure_file_hash_column()
        ensure_migration_tables()
