from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0079_sms_delivery_claim_and_unknown_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="smsdelivery",
            name="last_queued_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
