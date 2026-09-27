from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0057_formrepeatablegroup_label"),
    ]

    operations = [
        migrations.AddField(
            model_name="formfield",
            name="decimal_places",
            field=models.PositiveSmallIntegerField(default=2),
        ),
    ]
