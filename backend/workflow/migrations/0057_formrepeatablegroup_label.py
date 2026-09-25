from django.db import migrations, models


def populate_repeatable_group_labels(apps, schema_editor):
    FormRepeatableGroup = apps.get_model("workflow", "FormRepeatableGroup")

    for group in FormRepeatableGroup.objects.all().only("pk", "name", "label"):
        if not group.label:
            FormRepeatableGroup.objects.filter(pk=group.pk).update(
                label=group.name,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0056_remove_formfield_is_history_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="formrepeatablegroup",
            name="label",
            field=models.CharField(
                default="",
                max_length=200,
            ),
        ),
        migrations.RunPython(
            populate_repeatable_group_labels,
            migrations.RunPython.noop,
        ),
    ]
