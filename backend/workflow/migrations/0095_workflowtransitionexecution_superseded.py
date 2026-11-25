# Mark pending transitions as superseded when an administrator overrides the route.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0094_independent_workflow_instance_events"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workflowtransitionexecution",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "در انتظار تأیید"),
                    ("ACCEPTED", "تأیید شده"),
                    ("REJECTED", "رد شده"),
                    ("SUPERSEDED", "منسوخ‌شده بر اثر اصلاح مسیر"),
                ],
                default="ACCEPTED",
                max_length=20,
            ),
        ),
    ]
