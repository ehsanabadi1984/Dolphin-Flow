from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0058_formfield_decimal_places"),
    ]

    operations = [
        migrations.AddField(
            model_name="formfield",
            name="calendar",
            field=models.CharField(
                choices=[
                    ("GREGORIAN", "میلادی"),
                    ("JALALI", "شمسی"),
                ],
                default="GREGORIAN",
                max_length=10,
            ),
        ),
    ]
