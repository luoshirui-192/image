from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list = []

    operations = [
        migrations.CreateModel(
            name="ImageCategory",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category_name", models.CharField(default="", max_length=100)),
                ("sort", models.IntegerField(default=0)),
                ("create_time", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "image_category", "managed": False},
        ),
        migrations.CreateModel(
            name="ImageInfo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image_name", models.CharField(default="", max_length=255)),
                ("image_path", models.CharField(default="", max_length=500)),
                ("image_width", models.IntegerField(default=0)),
                ("image_height", models.IntegerField(default=0)),
                ("file_size", models.PositiveBigIntegerField(default=0)),
                ("file_suffix", models.CharField(default="", max_length=20)),
                ("upload_time", models.DateTimeField()),
                ("update_time", models.DateTimeField()),
                ("upload_user", models.CharField(default="", max_length=100)),
                ("is_delete", models.SmallIntegerField(default=0)),
                ("category_id", models.PositiveIntegerField(blank=True, null=True)),
                ("tags", models.CharField(default="", max_length=500)),
            ],
            options={"db_table": "image_info", "managed": False},
        ),
    ]
