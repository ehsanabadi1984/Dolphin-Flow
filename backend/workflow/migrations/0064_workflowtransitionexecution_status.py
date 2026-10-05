from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0063_workflowtransition_reject_to_step"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowtransitionexecution",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "در انتظار تأیید"),
                    ("ACCEPTED", "تأیید شده"),
                    ("REJECTED", "رد شده"),
                ],
                default="ACCEPTED",
                max_length=20,
            ),
        ),
    ]
