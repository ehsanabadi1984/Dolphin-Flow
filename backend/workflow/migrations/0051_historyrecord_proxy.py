from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0050_history_permission"),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoryRecord",
            fields=[],
            options={
                "verbose_name": "سابقه",
                "verbose_name_plural": "سوابق",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("workflow.workflowstepexecution",),
        ),
    ]
