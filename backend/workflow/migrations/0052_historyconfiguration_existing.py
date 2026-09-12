from django.db import migrations


def forwards(apps, schema_editor):
    FormDefinition = apps.get_model("workflow", "FormDefinition")
    HistoryConfiguration = apps.get_model("workflow", "HistoryConfiguration")
    HistoryField = apps.get_model("workflow", "HistoryField")
    FormField = apps.get_model("workflow", "FormField")

    for form in FormDefinition.objects.all().iterator():
        configuration, created = HistoryConfiguration.objects.get_or_create(
            form_id=form.pk,
            defaults={
                "name": f"History - {form.name}",
                "is_active": True,
            },
        )

        if not created:
            continue

        legacy_fields = (
            FormField.objects
            .filter(
                section__form_id=form.pk,
                section__is_active=True,
                is_active=True,
                is_history_enabled=True,
            )
            .order_by("section__order", "order", "id")
        )

        for display_order, field in enumerate(legacy_fields):
            HistoryField.objects.create(
                configuration_id=configuration.pk,
                form_field_id=field.pk,
                display_label=field.label,
                display_order=display_order,
                is_enabled=True,
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
