from django.apps import AppConfig


class ImagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "images"
    verbose_name = "图片与分类"

    def ready(self) -> None:
        from images.category_service import ensure_default_category
        from images.external_db_service import ensure_system_database_names
        from images.schema_ensure import ensure_file_hash_column, ensure_migration_tables

        ensure_system_database_names()
        ensure_file_hash_column()
        ensure_migration_tables()
        try:
            ensure_default_category()
        except Exception:
            import logging

            logging.getLogger(__name__).warning("ensure default category failed", exc_info=True)
