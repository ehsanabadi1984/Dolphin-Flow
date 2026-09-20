from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("backup", "0006_network_destination_connection"),
    ]

    operations = [
        migrations.CreateModel(
            name="BackupRetentionPolicy",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "enabled",
                    models.BooleanField(default=True, verbose_name="فعال"),
                ),
                (
                    "keep_last",
                    models.PositiveIntegerField(
                        default=10,
                        verbose_name="تعداد نسخه‌های اخیر",
                        help_text=(
                            "تعداد آخرین پشتیبان‌های موفق که همیشه حفظ می‌شوند. "
                            "صفر یعنی غیرفعال."
                        ),
                    ),
                ),
                (
                    "keep_days",
                    models.PositiveIntegerField(
                        default=30,
                        verbose_name="مدت نگهداری (روز)",
                        help_text=(
                            "پشتیبان‌های جدیدتر از این مدت حذف نمی‌شوند. "
                            "صفر یعنی غیرفعال."
                        ),
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="آخرین تغییر",
                    ),
                ),
            ],
            options={
                "verbose_name": "سیاست نگهداری پشتیبان",
                "verbose_name_plural": "سیاست نگهداری پشتیبان",
            },
        ),
    ]
