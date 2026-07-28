from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list = []

    operations = [
        migrations.CreateModel(
            name="OperateLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_id", models.PositiveIntegerField(blank=True, null=True)),
                ("username", models.CharField(default="", max_length=100)),
                ("action_type", models.CharField(default="", max_length=20)),
                ("sql_content", models.TextField(blank=True, null=True)),
                ("detail", models.CharField(default="", max_length=500)),
                ("ip", models.CharField(default="", max_length=50)),
                ("create_time", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "operate_log", "managed": False},
        ),
    ]
