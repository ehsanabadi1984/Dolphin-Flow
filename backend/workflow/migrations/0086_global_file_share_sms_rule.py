from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0085_sms_verification_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowsmssettings",
            name="file_share_sms_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "این قانون مستقل از تنظیمات پیامک مراحل است و فقط به "
                    "دریافت‌کنندگان انتخاب‌شده در File Sharing پیامک می‌فرستد."
                ),
                verbose_name="ارسال پیامک اشتراک‌گذاری فایل فعال باشد",
            ),
        ),
    ]
