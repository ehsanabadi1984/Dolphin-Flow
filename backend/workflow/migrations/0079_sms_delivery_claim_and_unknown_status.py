from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workflow", "0078_workflow_sms_settings_and_delivery")]

    operations = [
        migrations.AlterField(
            model_name="smsdelivery",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "در صف"),
                    ("SENDING", "در حال ارسال"),
                    ("SENT", "پذیرفته‌شده توسط درگاه"),
                    ("UNKNOWN", "وضعیت نامشخص؛ نیازمند بررسی"),
                    ("FAILED", "ناموفق"),
                    ("SKIPPED", "ارسال نشد"),
                ],
                default="PENDING",
                max_length=12,
            ),
        ),
    ]
