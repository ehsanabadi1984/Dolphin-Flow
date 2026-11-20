# Record the actual time an acceptance-required transition is resolved.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0090_workflowtransition_notification_recipient_policy"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowtransitionexecution",
            name="resolved_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="زمان تعیین تکلیف",
            ),
        ),
    ]
