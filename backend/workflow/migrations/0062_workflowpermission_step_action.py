from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0061_workflowtransition_requires_acceptance"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowpermission",
            name="action_code",
            field=models.CharField(
                blank=True,
                max_length=50,
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="workflowpermission",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        action="STEP_ACTION",
                        action_code__isnull=False,
                    )
                    | models.Q(
                        action__in=[
                            "VIEW",
                            "EXECUTE",
                            "START",
                            "TRANSITION",
                            "MANAGE",
                        ],
                        action_code__isnull=True,
                    )
                ),
                name="workflow_permission_step_action_code",
            ),
        ),
    ]
