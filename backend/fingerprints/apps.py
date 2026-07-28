from django.apps import AppConfig


class FingerprintsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fingerprints"
    verbose_name = "指纹成对对比"

    def ready(self) -> None:
        from fingerprints.schema_ensure import ensure_fingerprint_tables

        ensure_fingerprint_tables()
