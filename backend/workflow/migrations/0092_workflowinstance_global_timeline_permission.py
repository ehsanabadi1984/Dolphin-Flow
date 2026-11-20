# Add a dedicated Django permission for global workflow instance timelines.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0091_workflowtransitionexecution_resolved_at"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="workflowinstance",
            options={
                "ordering": ["-started_at"],
                "permissions": [
                    (
                        "view_all_workflowinstance_timelines",
                        "Can view all workflow instance timelines",
                    ),
                ],
            },
        ),
    ]
