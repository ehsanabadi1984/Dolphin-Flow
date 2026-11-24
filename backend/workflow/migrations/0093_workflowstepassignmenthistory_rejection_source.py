# Record the dedicated source for assignments selected during rejection.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0092_workflowinstance_global_timeline_permission"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workflowstepassignmenthistory",
            name="source",
            field=models.CharField(
                choices=[
                    ("INITIAL", "تخصیص اولیه"),
                    ("POLICY", "سیاست تخصیص"),
                    ("MANUAL", "تغییر دستی"),
                    ("ACCEPTANCE", "پذیرش مرحله"),
                    ("REJECTION", "تخصیص هنگام رد انتقال"),
                    ("OVERRIDE", "تغییر توسط مدیر"),
                ],
                max_length=20,
                verbose_name="منشأ تخصیص",
            ),
        ),
    ]
