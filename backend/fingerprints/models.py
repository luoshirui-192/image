from django.db import models


class FingerprintLayerType(models.Model):
    """Configurable feature-layer types (bidiso / neuiso / …)."""

    layer_key = models.CharField(max_length=64)
    label = models.CharField(max_length=100, default="")
    color = models.CharField(max_length=20, default="#e53935")
    suffixes = models.CharField(max_length=200, default="")  # comma-separated, e.g. bidiso,Bidiso
    default_algo_name = models.CharField(max_length=100, default="default")
    default_setlen = models.IntegerField(default=0)
    default_setang = models.IntegerField(default=256)
    sort_order = models.IntegerField(default=0)
    enabled = models.SmallIntegerField(default=1)
    create_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "fingerprint_layer_type"
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.label or self.layer_key

    def suffix_list(self) -> list[str]:
        return [s.strip().lower() for s in (self.suffixes or "").split(",") if s.strip()]


class FingerprintPair(models.Model):
    """Paired fingerprint impressions for side-by-side comparison."""

    batch_name = models.CharField(max_length=200, default="")
    finger_position = models.CharField(max_length=40, default="")
    match_score = models.FloatField(null=True, blank=True)
    left_image_id = models.PositiveBigIntegerField(default=0)
    right_image_id = models.PositiveBigIntegerField(default=0)
    left_person_id = models.CharField(max_length=64, default="")
    right_person_id = models.CharField(max_length=64, default="")
    left_image_name = models.CharField(max_length=255, default="")
    right_image_name = models.CharField(max_length=255, default="")
    source_dir = models.CharField(max_length=500, default="")
    upload_user = models.CharField(max_length=100, default="")
    tags = models.CharField(max_length=500, default="")
    is_delete = models.SmallIntegerField(default=0)
    create_time = models.DateTimeField(null=True, blank=True)
    update_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "fingerprint_pair"
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"{self.batch_name}:{self.finger_position}"


class FingerprintFeatureLayer(models.Model):
    """One feature template layer on one side of a pair."""

    pair_id = models.PositiveBigIntegerField()
    side = models.CharField(max_length=10, default="left")  # left|right panel
    layer_type = models.CharField(max_length=64, default="")
    algo_name = models.CharField(max_length=100, default="default")
    algo_version = models.CharField(max_length=64, default="1.0")
    template_path = models.CharField(max_length=500, default="")
    file_suffix = models.CharField(max_length=40, default="")
    file_hash = models.CharField(max_length=64, default="")
    file_size = models.PositiveBigIntegerField(default=0)
    setlen = models.IntegerField(default=0)
    setang = models.IntegerField(default=256)
    minutiae_count = models.IntegerField(default=0)
    minutiae_json = models.TextField(default="")  # optional decoded cache
    create_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "fingerprint_feature_layer"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.pair_id}:{self.side}:{self.layer_type}@{self.algo_version}"


class FingerprintImportJob(models.Model):
    """Background zip import for batmatch-style fingerprint packages."""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    zip_path = models.CharField(max_length=500, default="")
    zip_name = models.CharField(max_length=255, default="")
    status = models.CharField(max_length=20, default=STATUS_PENDING)
    algo_version = models.CharField(max_length=64, default="1.0")
    tags = models.CharField(max_length=500, default="")
    skip_existing = models.SmallIntegerField(default=1)
    category_id = models.PositiveIntegerField(null=True, blank=True)
    total_estimate = models.PositiveIntegerField(default=0)
    processed = models.PositiveIntegerField(default=0)
    succeeded = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    cancel_requested = models.SmallIntegerField(default=0)
    message = models.CharField(max_length=500, default="")
    last_error = models.CharField(max_length=500, default="")
    result_json = models.TextField(null=True, blank=True)
    created_by = models.CharField(max_length=100, default="")
    create_time = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "fingerprint_import_job"
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"fp-import-{self.id}:{self.status}"
