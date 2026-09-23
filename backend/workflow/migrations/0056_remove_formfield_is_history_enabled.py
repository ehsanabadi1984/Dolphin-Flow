from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0055_repeatable_row_and_values"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="formfield",
            name="is_history_enabled",
        ),
    ]
