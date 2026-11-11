from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0076_alter_workflowpermission_action"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkflowStepSMSRule",
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
                    "notification_type",
                    models.CharField(
                        choices=[
                            ("WORKFLOW_STARTED", "شروع فرآیند"),
                            ("STEP_ENTERED", "ورود به مرحله"),
                            ("TRANSITION_EXECUTED", "تغییر مرحله"),
                            ("ACTION_REQUIRED", "نیاز به اقدام"),
                            ("WORKFLOW_COMPLETED", "تکمیل فرآیند"),
                            ("WORKFLOW_CANCELLED", "لغو فرآیند"),
                            ("SLA_WARNING", "هشدار SLA"),
                            ("SLA_BREACHED", "نقض SLA"),
                            ("FILE_SHARE_MESSAGE", "پیام اشتراک‌گذاری فایل"),
                        ],
                        max_length=30,
                        verbose_name="نوع اعلان",
                    ),
                ),
                (
                    "sms_enabled",
                    models.BooleanField(
                        default=False,
                        verbose_name="ارسال پیامک فعال باشد",
                    ),
                ),
                (
                    "step",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sms_rules",
                        to="workflow.workflowstep",
                        verbose_name="مرحله",
                    ),
                ),
            ],
            options={
                "verbose_name": "تنظیم پیامک مرحله",
                "verbose_name_plural": "تنظیمات پیامک مرحله",
                "ordering": ("notification_type",),
            },
        ),
        migrations.AddConstraint(
            model_name="workflowstepsmsrule",
            constraint=models.UniqueConstraint(
                fields=("step", "notification_type"),
                name="unique_step_sms_notification_rule",
            ),
        ),
    ]
