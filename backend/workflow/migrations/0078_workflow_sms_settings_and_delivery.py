import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0077_workflow_step_sms_rules"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkflowSMSSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_enabled", models.BooleanField(default=False, verbose_name="ارسال پیامک فعال باشد")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "تنظیم سراسری پیامک",
                "verbose_name_plural": "تنظیمات سراسری پیامک",
            },
        ),
        migrations.CreateModel(
            name="SMSDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("PENDING", "در صف / در حال ارسال"), ("SENT", "پذیرفته‌شده توسط درگاه"), ("FAILED", "ناموفق"), ("SKIPPED", "ارسال نشد")], default="PENDING", max_length=12)),
                ("provider_uid", models.PositiveBigIntegerField(blank=True, null=True)),
                ("provider_message_id", models.CharField(blank=True, max_length=64)),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("last_error", models.TextField(blank=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("notification", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="sms_delivery", to="workflow.notification", verbose_name="اعلان")),
            ],
            options={
                "verbose_name": "ارسال پیامک",
                "verbose_name_plural": "سوابق فنی ارسال پیامک",
                "ordering": ("-created_at",),
            },
        ),
    ]
