from django.db import migrations


def forwards(apps, schema_editor):
    FormDefinition = apps.get_model("workflow", "FormDefinition")
    HistoryConfiguration = apps.get_model("workflow", "HistoryConfiguration")

    for form in FormDefinition.objects.all().iterator():
        HistoryConfiguration.objects.get_or_create(
            form_id=form.pk,
            defaults={
                "name": f"History - {form.name}",
                "is_active": True,
            },
        )


def backwards(apps, schema_editor):
    # Existing configurations may have been edited manually after this
    # migration. Do not delete them on rollback.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0051_historyrecord_proxy"),
    ]

    operations = [
        migrations.RunPython(
            forwards,
            backwards,
        ),
    ]
