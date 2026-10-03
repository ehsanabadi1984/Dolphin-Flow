from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0060_access_edit_requires_view"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowtransition",
            name="requires_acceptance",
            field=models.BooleanField(default=False),
        ),
    ]
