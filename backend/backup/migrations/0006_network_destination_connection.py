from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("backup", "0005_backupstoragedestination_backup_network_storage"),
    ]

    operations = [
        migrations.RenameField(
            model_name="backupstoragedestination",
            old_name="root_path",
            new_name="remote_path",
        ),
        migrations.AddField(
            model_name="backupstoragedestination",
            name="host",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="آدرس سرور",
                help_text="IP یا نام DNS مقصد؛ مثلاً 192.168.1.50",
            ),
        ),
        migrations.AddField(
            model_name="backupstoragedestination",
            name="port",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                verbose_name="پورت",
                help_text="در صورت خالی بودن، پورت پیش‌فرض پروتکل استفاده می‌شود.",
            ),
        ),
        migrations.AddField(
            model_name="backupstoragedestination",
            name="share",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="نام Share",
                help_text="برای SMB؛ مثلاً DolphinBackup",
            ),
        ),
        migrations.AddField(
            model_name="backupstoragedestination",
            name="username",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="نام کاربری",
            ),
        ),
        migrations.AddField(
            model_name="backupstoragedestination",
            name="encrypted_password",
            field=models.TextField(
                blank=True,
                editable=False,
                verbose_name="رمزنگاری‌شده",
            ),
        ),
        migrations.AlterField(
            model_name="backupstoragedestination",
            name="backend_type",
            field=models.CharField(
                choices=[
                    ("SMB", "SMB"),
                    ("SFTP", "SFTP"),
                    ("MOUNTED_FOLDER", "پوشه Mount شده (Legacy)"),
                ],
                default="SMB",
                max_length=20,
                verbose_name="نوع اتصال",
            ),
        ),
        migrations.AlterField(
            model_name="backupstoragedestination",
            name="remote_path",
            field=models.CharField(
                blank=True,
                max_length=512,
                verbose_name="مسیر مقصد",
                help_text="مسیر داخل Share در SMB یا مسیر پوشه در SFTP.",
            ),
        ),
    ]
