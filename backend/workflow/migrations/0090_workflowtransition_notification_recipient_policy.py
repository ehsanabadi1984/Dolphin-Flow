# Generated for independent ACCEPT/REJECT notification recipient policies.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0089_workflowtransitionexecution_proposed_assignee"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowtransition",
            name="accept_notification_policy",
            field=models.CharField(
                choices=[
                    ("SOURCE_COMPLETER", "تکمیل‌کننده اجرای مبدأ"),
                    ("FIXED_USER", "کاربر ثابت"),
                    ("RETURN_STEP_ASSIGNEE", "مسئول مرحله مقصد/بازگشت"),
                    ("WORKFLOW_STARTER", "شروع‌کننده فرآیند"),
                ],
                default="SOURCE_COMPLETER",
                max_length=32,
                verbose_name="سیاست گیرنده اعلان پذیرش",
            ),
        ),
        migrations.AddField(
            model_name="workflowtransition",
            name="accept_notification_user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workflow_transition_accept_notification_targets",
                to=settings.AUTH_USER_MODEL,
                verbose_name="گیرنده ثابت اعلان پذیرش",
            ),
        ),
        migrations.AddField(
            model_name="workflowtransition",
            name="reject_notification_policy",
            field=models.CharField(
                choices=[
                    ("SOURCE_COMPLETER", "تکمیل‌کننده اجرای مبدأ"),
                    ("FIXED_USER", "کاربر ثابت"),
                    ("RETURN_STEP_ASSIGNEE", "مسئول مرحله مقصد/بازگشت"),
                    ("WORKFLOW_STARTER", "شروع‌کننده فرآیند"),
                ],
                default="SOURCE_COMPLETER",
                max_length=32,
                verbose_name="سیاست گیرنده اعلان رد",
            ),
        ),
        migrations.AddField(
            model_name="workflowtransition",
            name="reject_notification_user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workflow_transition_reject_notification_targets",
                to=settings.AUTH_USER_MODEL,
                verbose_name="گیرنده ثابت اعلان رد",
            ),
        ),
        migrations.CreateModel(
            name="WorkflowTransitionNotificationIssue",
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
                    "outcome",
                    models.CharField(
                        choices=[("ACCEPT", "پذیرش"), ("REJECT", "رد")],
                        max_length=10,
                        verbose_name="نتیجه انتقال",
                    ),
                ),
                (
                    "policy",
                    models.CharField(
                        choices=[
                            ("SOURCE_COMPLETER", "تکمیل‌کننده اجرای مبدأ"),
                            ("FIXED_USER", "کاربر ثابت"),
                            ("RETURN_STEP_ASSIGNEE", "مسئول مرحله مقصد/بازگشت"),
                            ("WORKFLOW_STARTER", "شروع‌کننده فرآیند"),
                        ],
                        max_length=32,
                        verbose_name="سیاست گیرنده",
                    ),
                ),
                (
                    "error_code",
                    models.CharField(
                        max_length=64,
                        verbose_name="کد خطا",
                    ),
                ),
                (
                    "details",
                    models.TextField(verbose_name="شرح خطا"),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="زمان ثبت",
                    ),
                ),
                (
                    "transition_execution",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="notification_issues",
                        to="workflow.workflowtransitionexecution",
                        verbose_name="اجرای انتقال",
                    ),
                ),
            ],
            options={
                "verbose_name": "خطای تعیین گیرنده اعلان انتقال",
                "verbose_name_plural": "خطاهای تعیین گیرنده اعلان انتقال",
                "ordering": ["-created_at", "-pk"],
            },
        ),
        migrations.AddConstraint(
            model_name="workflowtransition",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        accept_notification_policy="FIXED_USER",
                        accept_notification_user__isnull=False,
                    )
                    | (
                        ~models.Q(accept_notification_policy="FIXED_USER")
                        & models.Q(accept_notification_user__isnull=True)
                    )
                ),
                name="wf_trans_accept_notif_user_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="workflowtransition",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        reject_notification_policy="FIXED_USER",
                        reject_notification_user__isnull=False,
                    )
                    | (
                        ~models.Q(reject_notification_policy="FIXED_USER")
                        & models.Q(reject_notification_user__isnull=True)
                    )
                ),
                name="wf_trans_reject_notif_user_ck",
            ),
        ),
    ]
