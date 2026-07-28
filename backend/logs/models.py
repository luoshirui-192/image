from django.db import models


class OperateLog(models.Model):
    user_id = models.PositiveIntegerField(null=True, blank=True)
    username = models.CharField(max_length=100, default="")
    action_type = models.CharField(max_length=20, default="")
    sql_content = models.TextField(null=True, blank=True)
    detail = models.CharField(max_length=500, default="")
    ip = models.CharField(max_length=50, default="")
    create_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "operate_log"
        verbose_name = "操作日志"
        verbose_name_plural = "操作日志"
        ordering = ["-create_time", "-id"]
        indexes = [
            models.Index(fields=["user_id"], name="idx_user_id"),
            models.Index(fields=["action_type"], name="idx_action_type"),
            models.Index(fields=["create_time"], name="idx_create_time"),
        ]

    def __str__(self) -> str:
        return f"{self.username}:{self.action_type}"
