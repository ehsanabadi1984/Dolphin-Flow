from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0059_formfield_calendar"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="fieldaccess",
            constraint=models.CheckConstraint(
                condition=models.Q(can_edit=False) | models.Q(can_view=True),
                name="field_access_edit_requires_view",
            ),
        ),
        migrations.AddConstraint(
            model_name="repeatablegroupaccess",
            constraint=models.CheckConstraint(
                condition=models.Q(can_edit=False) | models.Q(can_view=True),
                name="repeatable_group_access_edit_requires_view",
            ),
        ),
    ]
