from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("backup", "0003_backup_source_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="BackupSchedule",
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
                    "name",
                    models.CharField(max_length=150, verbose_name="نام زمان‌بندی"),
                ),
                (
                    "enabled",
                    models.BooleanField(default=True, verbose_name="فعال"),
                ),
                (
                    "frequency",
                    models.CharField(
                        choices=[
                            ("ONCE", "یک‌بار"),
                            ("DAILY", "روزانه"),
                            ("WEEKLY", "هفتگی"),
                            ("MONTHLY", "ماهانه"),
                            ("INTERVAL", "دوره‌ای"),
                        ],
                        max_length=20,
                        verbose_name="نوع زمان‌بندی",
                    ),
                ),
                (
                    "run_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="برای اجرای یک‌باره استفاده می‌شود.",
                        null=True,
                        verbose_name="زمان اجرا",
                    ),
                ),
                (
                    "time_of_day",
                    models.TimeField(
                        blank=True,
                        null=True,
                        verbose_name="ساعت اجرا",
                    ),
                ),
                (
                    "weekday",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        choices=[
                            (0, "دوشنبه"),
                            (1, "سه‌شنبه"),
                            (2, "چهارشنبه"),
                            (3, "پنج‌شنبه"),
                            (4, "جمعه"),
                            (5, "شنبه"),
                            (6, "یکشنبه"),
                        ],
                        null=True,
                        verbose_name="روز هفته",
                    ),
                ),
                (
                    "day_of_month",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        null=True,
                        verbose_name="روز ماه",
                    ),
                ),
                (
                    "interval_minutes",
                    models.PositiveIntegerField(
                        blank=True,
                        null=True,
                        verbose_name="فاصله اجرا (دقیقه)",
                    ),
                ),
                (
                    "starts_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="برای زمان‌بندی دوره‌ای، نقطه شروع محاسبه فاصله اجرا.",
                        null=True,
                        verbose_name="شروع دوره‌ای",
                    ),
                ),
                (
                    "include_media",
                    models.BooleanField(
                        default=True,
                        verbose_name="شامل فایل‌های رسانه",
                    ),
                ),
                (
                    "destination",
                    models.CharField(
                        choices=[
                            ("LOCAL", "محلی"),
                            ("NETWORK", "شبکه"),
                            ("BOTH", "محلی + شبکه"),
                        ],
                        default="LOCAL",
                        max_length=20,
                        verbose_name="مقصد",
                    ),
                ),
                (
                    "last_run_at",
                    models.DateTimeField(
                        blank=True,
                        editable=False,
                        null=True,
                        verbose_name="آخرین اجرا",
                    ),
                ),
                (
                    "next_run_at",
                    models.DateTimeField(
                        blank=True,
                        editable=False,
                        null=True,
                        verbose_name="اجرای بعدی",
                    ),
                ),
                (
                    "last_status",
                    models.CharField(
                        blank=True,
                        editable=False,
                        max_length=20,
                        verbose_name="وضعیت آخرین اجرا",
                    ),
                ),
                (
                    "last_error",
                    models.TextField(
                        blank=True,
                        editable=False,
                        verbose_name="خطای آخرین اجرا",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="ایجاد شده",
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
                "verbose_name": "زمان‌بندی پشتیبان‌گیری",
                "verbose_name_plural": "زمان‌بندی‌های پشتیبان‌گیری",
                "ordering": ["name", "-created_at"],
            },
        ),
        migrations.AddField(
            model_name="backup",
            name="destination",
            field=models.CharField(
                choices=[
                    ("LOCAL", "محلی"),
                    ("NETWORK", "شبکه"),
                    ("BOTH", "محلی + شبکه"),
                ],
                default="LOCAL",
                max_length=20,
                verbose_name="مقصد",
            ),
        ),
        migrations.AddField(
            model_name="backup",
            name="network_checksum",
            field=models.CharField(
                blank=True,
                max_length=64,
                verbose_name="SHA-256 شبکه",
            ),
        ),
        migrations.AddField(
            model_name="backup",
            name="network_copied_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="زمان انتقال شبکه",
            ),
        ),
        migrations.AddField(
            model_name="backup",
            name="network_error",
            field=models.TextField(
                blank=True,
                verbose_name="خطای انتقال شبکه",
            ),
        ),
        migrations.AddField(
            model_name="backup",
            name="network_size",
            field=models.BigIntegerField(
                blank=True,
                null=True,
                verbose_name="حجم فایل شبکه",
            ),
        ),
        migrations.AddField(
            model_name="backup",
            name="network_status",
            field=models.CharField(
                choices=[
                    ("NOT_REQUESTED", "بدون انتقال شبکه"),
                    ("PENDING", "در انتظار انتقال"),
                    ("SUCCESS", "انتقال موفق"),
                    ("FAILED", "انتقال ناموفق"),
                ],
                default="NOT_REQUESTED",
                max_length=20,
                verbose_name="وضعیت انتقال شبکه",
            ),
        ),
        migrations.AddField(
            model_name="backup",
            name="network_storage_path",
            field=models.CharField(
                blank=True,
                max_length=512,
                verbose_name="مسیر شبکه",
            ),
        ),
        migrations.AddField(
            model_name="backup",
            name="schedule",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="backups",
                to="backup.backupschedule",
                verbose_name="زمان‌بندی",
            ),
        ),
    ]
