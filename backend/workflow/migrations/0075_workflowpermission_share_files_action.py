# Add the step-scoped file-sharing action to WorkflowPermission.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0074_file_share_drafts"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workflowpermission",
            name="action",
            field=models.CharField(
                choices=[
                    ("VIEW", "مشاهده"),
                    ("EXECUTE", "اجرا"),
                    ("START", "شروع فرآیند"),
                    ("TRANSITION", "تغییر مرحله"),
                    ("MANAGE", "مدیریت"),
                    ("STEP_ACTION", "عملیات مرحله"),
                    ("SHARE_FILES", "اشتراک‌گذاری فایل"),
                ],
                max_length=20,
            ),
        ),
    ]
