from django.contrib.auth.hashers import check_password, make_password
from django.db import models


class SysUser(models.Model):
    """Maps to existing table sys_user (managed=False, no last_login column)."""

    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=100, unique=True)
    password = models.CharField(max_length=128)
    role = models.CharField(max_length=20, default="user")
    status = models.SmallIntegerField(default=1)
    create_time = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        managed = False
        db_table = "sys_user"
        verbose_name = "系统用户"
        verbose_name_plural = "系统用户"
        indexes = [
            models.Index(fields=["status", "role"], name="idx_status_role"),
        ]

    def __str__(self) -> str:
        return self.username

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    @property
    def is_active(self) -> bool:
        return self.status == 1

    @property
    def is_staff(self) -> bool:
        return self.role == "admin"

    @property
    def is_superuser(self) -> bool:
        return self.role == "admin"

    def check_password(self, raw_password: str) -> bool:
        return check_password(raw_password, self.password)

    def set_password(self, raw_password: str) -> None:
        self.password = make_password(raw_password)

    def has_perm(self, perm, obj=None) -> bool:
        return self.is_superuser

    def has_module_perms(self, app_label) -> bool:
        return self.is_superuser
