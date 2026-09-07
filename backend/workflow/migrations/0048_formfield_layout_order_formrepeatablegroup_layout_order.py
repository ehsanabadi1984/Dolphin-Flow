from django.db import migrations, models


def backfill_layout_order(apps, schema_editor):
    """
    Assign deterministic ``layout_order`` values to existing records.

    The current application renders every section as:

        all top-level fields (in ``order`` sequence)
        then all repeatable groups (in ``order`` sequence)

    To preserve exactly that behavior the backfill places every
    top-level field before every group:

        top-level fields:     10, 20, 30, ...   (in ``order`` sequence)
        repeatable groups:   100, 110, 120, ... (in ``order`` sequence)

    The group range starts at max(100, ...) so a section with ten or
    more top-level fields can never collide with the group range.
    Existing ``order`` values are never modified.
    """
    FormField = apps.get_model("workflow", "FormField")
    FormRepeatableGroup = apps.get_model("workflow", "FormRepeatableGroup")

    section_ids = (
        set(
            FormField.objects
            .filter(repeatable_group__isnull=True)
            .values_list("section_id", flat=True)
        )
        | set(
            FormRepeatableGroup.objects
            .values_list("section_id", flat=True)
        )
    )

    for section_id in section_ids:

        # Top-level fields only: fields inside a repeatable group
        # are never part of the section's top-level layout.
        fields = list(
            FormField.objects
            .filter(
                section_id=section_id,
                repeatable_group__isnull=True,
            )
            .order_by("order", "id")
        )

        for index, field in enumerate(fields):
            field.layout_order = (index + 1) * 10

        if fields:
            FormField.objects.bulk_update(fields, ["layout_order"])

        groups = list(
            FormRepeatableGroup.objects
            .filter(section_id=section_id)
            .order_by("order", "id")
        )

        # Guarantee every group sorts after every field of the
        # section, even for sections with many fields.
        group_base = max(
            100,
            (len(fields) + 1) * 10,
        )

        for index, group in enumerate(groups):
            group.layout_order = group_base + index * 10

        if groups:
            FormRepeatableGroup.objects.bulk_update(
                groups,
                ["layout_order"],
            )


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0047_alter_formfield_field_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="formfield",
            name="layout_order",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="formrepeatablegroup",
            name="layout_order",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
            ),
        ),
        migrations.RunPython(
            backfill_layout_order,
            migrations.RunPython.noop,
        ),
    ]