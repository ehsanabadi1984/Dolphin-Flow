from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("backup", "0004_backupschedule_backup_network"),
    ]

    operations = [
        migrations.CreateModel(
            name="BackupStorageDestination",
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
                    models.CharField(max_length=150, unique=True, verbose_name="نام مقصد"),
                ),
                (
                    "backend_type",
                    models.CharField(
                        choices=[
                            ("MOUNTED_FOLDER", "پوشه Mount شده"),
                            ("SMB", "SMB"),
                            ("NFS", "NFS"),
                        ],
                        default="MOUNTED_FOLDER",
                        max_length=20,
                        verbose_name="نوع مقصد",
                    ),
                ),
                (
                    "root_path",
                    models.CharField(
                        help_text="مسیر محلی Mount شده روی سرور؛ اتصال SMB/NFS خارج از Django مدیریت می‌شود.",
                        max_length=512,
                        verbose_name="مسیر Mount",
                    ),
                ),
                ("enabled", models.BooleanField(default=True, verbose_name="فعال")),
                ("description", models.TextField(blank=True, verbose_name="توضیحات")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="ایجاد شده")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")),
            ],
            options={
                "verbose_name": "مقصد ذخیره‌سازی شبکه",
                "verbose_name_plural": "مقصدهای ذخیره‌سازی شبکه",
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="backupschedule",
            name="network_storage",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="schedules",
                to="backup.backupstoragedestination",
                verbose_name="مقصد شبکه",
            ),
        ),
        migrations.AddField(
            model_name="backup",
            name="network_storage",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="backups",
                to="backup.backupstoragedestination",
                verbose_name="مقصد شبکه",
            ),
        ),
    ]
