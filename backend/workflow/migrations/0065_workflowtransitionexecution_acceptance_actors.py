from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0064_workflowtransitionexecution_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowtransitionexecution",
            name="accepted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="accepted_workflow_transition_executions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="workflowtransitionexecution",
            name="rejected_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="rejected_workflow_transition_executions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
