# Generated for internal file-share pre-submit drafts.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("workflow", "0073_shared_file_asset_cleanup_state"),
    ]
    operations = [
        migrations.CreateModel(
            name="FileShareDraft",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("interaction_type", models.CharField(choices=[("VIEW", "اشتراک‌گذاری برای مشاهده"), ("RESPONSE", "درخواست پاسخ یا دریافت اطلاعات"), ("ACTION", "درخواست انجام اقدام"), ("REVIEW", "درخواست بررسی یا تأیید فایل")], default="VIEW", max_length=20)),
                ("subject", models.CharField(blank=True, default="", max_length=200)),
                ("body", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("DRAFT", "پیش‌نویس"), ("CONVERTED", "تبدیل‌شده به پیام")], default="DRAFT", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("converted_at", models.DateTimeField(blank=True, null=True)),
                ("file_share_message", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="source_draft", to="workflow.filesharemessage")),
                ("form_file", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="share_drafts", to="workflow.formfile")),
                ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="file_share_drafts_received", to=settings.AUTH_USER_MODEL)),
                ("sender", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="file_share_drafts_sent", to=settings.AUTH_USER_MODEL)),
                ("workflow_instance", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="file_share_drafts", to="workflow.workflowinstance")),
                ("workflow_step", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="file_share_drafts", to="workflow.workflowstep")),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
        migrations.AddConstraint(
            model_name="filesharedraft",
            constraint=models.CheckConstraint(
                condition=(models.Q(status="DRAFT", form_file__isnull=False, file_share_message__isnull=True, converted_at__isnull=True) | models.Q(status="CONVERTED", form_file__isnull=True, file_share_message__isnull=False, converted_at__isnull=False)),
                name="fshare_draft_state_consistent",
            ),
        ),
    ]
