from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0062_workflowpermission_step_action"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowtransition",
            name="reject_to_step",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="acceptance_reject_target_transitions",
                to="workflow.workflowstep",
            ),
        ),
    ]
