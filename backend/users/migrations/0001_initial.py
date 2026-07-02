# Generated for managed=False model state
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list = []

    operations = [
        migrations.CreateModel(
            name="SysUser",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("username", models.CharField(max_length=100, unique=True)),
                ("role", models.CharField(default="user", max_length=20)),
                ("status", models.SmallIntegerField(default=1)),
                ("create_time", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "sys_user",
                "managed": False,
            },
        ),
    ]
