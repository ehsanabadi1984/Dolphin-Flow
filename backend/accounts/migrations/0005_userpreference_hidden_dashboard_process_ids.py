from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_userpreference"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreference",
            name="hidden_dashboard_process_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
