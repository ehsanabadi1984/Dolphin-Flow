# Generated for provisional destination assignee selection.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0088_workflowstep_assignment_policy_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowtransitionexecution",
            name="proposed_assignee",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="proposed_workflow_transition_executions",
                to=settings.AUTH_USER_MODEL,
                verbose_name="مسئول پیشنهادی مرحله مقصد",
            ),
        ),
    ]
