from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("backup", "0002_backup_is_pre_restore_backup_restore"),
    ]

    operations = [
        migrations.AddField(
            model_name="backup",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("LOCAL_CREATED", "ایجاد محلی"),
                    ("IMPORTED", "وارد شده"),
                ],
                default="LOCAL_CREATED",
                help_text="منبع ایجاد این پشتیبان.",
                max_length=20,
            ),
        ),
    ]